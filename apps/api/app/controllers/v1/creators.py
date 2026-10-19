"""Creator Profiles + Follow Graph + Leaderboards v1 API controller.

Endpoints under ``/api/v1`` for public creator identity, a directed follow graph
and a documented, deterministic reputation leaderboard:

* ``GET    /creators/leaderboard`` — **PUBLIC**: creators ranked by ``metric``
  (``reputation`` default; ``followers`` | ``clones`` | ``rating`` | ``published``
  | ``win_score``), ``limit`` clamped to ``[1, 100]``. Registered BEFORE the
  ``{handle_or_id}`` route so ``leaderboard`` is never captured as a handle.
* ``GET    /creators/{handle_or_id}`` — **PUBLIC**: a creator's SAFE public
  profile (resolvable by id OR handle). Unknown → ``404``.
* ``POST   /creators/{id}/follow`` — auth, caller-scoped: idempotently follow a
  creator. Self-follow → ``400``; unknown followee → ``404``.
* ``DELETE /creators/{id}/follow`` — auth, caller-scoped: unfollow (idempotent).
* ``GET    /me/following`` — auth: the SAFE public profiles the caller follows.
* ``PATCH  /me/profile`` — auth: set the caller's own ``handle`` / ``display_name``
  / ``bio``. A taken handle is a clean ``409``.

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard behind the single ``base.verify_token`` gate). The PUBLIC profile +
  leaderboard endpoints deliberately skip ``_resolve_user`` so they are reachable
  without an api key.
* **Import-safe optional deps.** The creators service + follow model are imported
  inside guarded blocks; when absent the endpoints degrade to a clean ``503``.
* **Clean 4xx over 422.** A service ``ValueError`` (blank id / self-follow) →
  ``400``; a ``LookupError`` (unknown creator) → ``404``.
* **Safe public surface.** The profile / leaderboard / following DTOs are STRICT
  pydantic models (no ``extra="allow"``) so a private field (credits/email/cost/
  revenue) can never leak — mirroring ``creators.SAFE_PROFILE_FIELDS``.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`. No secrets are hardcoded.
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Query, Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    CreatorProfileResponse,
    FollowingListResponse,
    FollowResponse,
    LeaderboardResponse,
    ProfileUpdateRequest,
    ProfileUpdateResponse,
)
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded optional imports (depend on the DB layer authored by sibling agents;
# may be absent at compile time). Keeping these guarded makes the module
# import-safe: a missing dependency degrades to a clean 503 at request time.
# --------------------------------------------------------------------------- #
try:
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from app.models.db.models import CreatorFollow, User
    from app.services import creators as creators_service

    _CREATORS_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    select = None  # type: ignore[assignment]
    IntegrityError = None  # type: ignore[assignment,misc]
    CreatorFollow = None  # type: ignore[assignment,misc]
    User = None  # type: ignore[assignment,misc]
    creators_service = None  # type: ignore[assignment]
    _CREATORS_IMPORT_ERROR = exc


router = new_router()

# --------------------------------------------------------------------------- #
# Tunables (config-overridable). Follows write a DB row, so they are capped
# per-caller to prevent unbounded insert (follow-spam) abuse. The limiter degrades
# OPEN when Redis is unreachable, so it never breaks the flow.
# --------------------------------------------------------------------------- #
_DEFAULT_FOLLOW_RATE_LIMIT: int = 300
_DEFAULT_FOLLOW_RATE_WINDOW_S: int = 3600
#: Cap on how many followed creators ``GET /me/following`` resolves in one call, so
#: a heavily-following account can never trigger an unbounded profile fan-out.
_MAX_FOLLOWING: int = 100


def _follow_rate_limit() -> int:
    return int(
        config.app.get("reelforge_follow_rate_limit", _DEFAULT_FOLLOW_RATE_LIMIT)
    )


def _follow_rate_window_s() -> int:
    return int(
        config.app.get(
            "reelforge_follow_rate_window_s", _DEFAULT_FOLLOW_RATE_WINDOW_S
        )
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_creators(request_id: str) -> None:
    """Raise 503 when the creators service/layer could not be imported."""
    if creators_service is None or CreatorFollow is None or User is None:
        logger.error(
            f"creators layer unavailable, request_id: {request_id}, "
            f"error: {_CREATORS_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: creator profiles are not available",
        )


# --------------------------------------------------------------------------- #
# GET /creators/leaderboard  (PUBLIC — clamped)  [registered BEFORE {id} route]
# --------------------------------------------------------------------------- #
@router.get(
    "/creators/leaderboard",
    response_model=LeaderboardResponse,
    summary="Public creator leaderboard (ranked by a documented metric)",
)
def leaderboard_endpoint(
    request: Request,
    metric: str = Query(
        default="reputation",
        max_length=32,
        description="reputation | followers | clones | rating | published | win_score",
    ),
    limit: int = Query(default=20, description="Page size (clamped to 1..100)"),
):
    """Return creators ranked by ``metric`` DESC (``user_id`` tie-break), clamped.

    PUBLIC (no auth). ``metric`` normalises to ``reputation`` on an unknown value
    and ``limit`` is clamped to ``[1, 100]`` in the service so an untrusted request
    can never trigger an unbounded scan. Every entry exposes ONLY safe fields
    (aggregates + score + rank + addressing ``user_id``/``handle``) — never
    credits/email/cost/revenue.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_creators(request_id)

    with get_session() as session:
        data = creators_service.leaderboard(session, metric=metric, limit=limit)

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /creators/{handle_or_id}  (PUBLIC safe profile)
# --------------------------------------------------------------------------- #
@router.get(
    "/creators/{handle_or_id}",
    response_model=CreatorProfileResponse,
    summary="Public creator profile (by handle or id)",
)
def creator_profile_endpoint(
    request: Request,
    handle_or_id: str = Path(..., description="Creator handle OR user id"),
):
    """Return a creator's SAFE public profile (PUBLIC — no auth). Unknown → ``404``.

    Resolvable by ``user_id`` OR public ``handle``. The response is a STRICT safe
    DTO — it NEVER exposes credits, email, cost/revenue, ``user_id`` or any other
    private field.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_creators(request_id)

    try:
        with get_session() as session:
            data = creators_service.public_profile(session, handle_or_id)
    except ValueError as exc:
        raise HttpException(
            task_id=request_id, status_code=400, message=str(exc)
        )
    except LookupError:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: creator not found",
        )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# POST /creators/{id}/follow  (auth, caller-scoped)
# --------------------------------------------------------------------------- #
@router.post(
    "/creators/{creator_id}/follow",
    response_model=FollowResponse,
    summary="Follow a creator",
)
def follow_endpoint(
    request: Request,
    creator_id: str = Path(..., description="The creator (user id) to follow"),
):
    """Idempotently follow a creator (auth, caller-scoped).

    A user can never follow themselves (``400``); an unknown followee is a
    ``404``. Following someone already followed is a harmless no-op reporting the
    current state.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_creators(request_id)

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            enforce_rate_limit(
                request,
                f"creator_follow:{user.id}",
                limit=_follow_rate_limit(),
                window_s=_follow_rate_window_s(),
            )
            data = creators_service.follow(session, user.id, creator_id)
    except HttpException:
        raise
    except ValueError as exc:
        # Blank id or self-follow -> clean 400.
        raise HttpException(
            task_id=request_id, status_code=400, message=str(exc)
        )
    except LookupError:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: creator not found",
        )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# DELETE /creators/{id}/follow  (auth, caller-scoped)
# --------------------------------------------------------------------------- #
@router.delete(
    "/creators/{creator_id}/follow",
    response_model=FollowResponse,
    summary="Unfollow a creator",
)
def unfollow_endpoint(
    request: Request,
    creator_id: str = Path(..., description="The creator (user id) to unfollow"),
):
    """Remove the caller's follow edge (idempotent, caller-scoped).

    Unfollowing someone the caller does not follow is a harmless no-op
    (``removed`` is ``False``). A blank id is a clean ``400``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_creators(request_id)

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            data = creators_service.unfollow(session, user.id, creator_id)
    except HttpException:
        raise
    except ValueError as exc:
        raise HttpException(
            task_id=request_id, status_code=400, message=str(exc)
        )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /me/following  (auth)
# --------------------------------------------------------------------------- #
@router.get(
    "/me/following",
    response_model=FollowingListResponse,
    summary="List the safe public profiles the caller follows",
)
def following_endpoint(request: Request):
    """Return the SAFE public profiles of the creators the caller follows.

    Bounded to :data:`_MAX_FOLLOWING` followees (newest edge first) so a heavily
    following account can never trigger an unbounded profile fan-out. Each entry is
    the same STRICT safe profile DTO as ``GET /creators/{id}`` — never a private
    field. A followee whose account has since been deleted is skipped silently.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_creators(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        stmt = (
            select(CreatorFollow.followee_user_id)
            .where(CreatorFollow.follower_user_id == user.id)
            .order_by(CreatorFollow.created_at.desc(), CreatorFollow.id.desc())
            .limit(_MAX_FOLLOWING)
        )
        followee_ids = [row[0] for row in session.execute(stmt).all()]
        data: list[dict[str, Any]] = []
        for followee_id in followee_ids:
            try:
                data.append(creators_service.public_profile(session, followee_id))
            except LookupError:
                # A followed account was deleted — skip it rather than 500.
                continue

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# PATCH /me/profile  (auth — set handle / display_name / bio)
# --------------------------------------------------------------------------- #
@router.patch(
    "/me/profile",
    response_model=ProfileUpdateResponse,
    summary="Update your own public profile (handle / display_name / bio)",
)
def update_profile_endpoint(request: Request, body: ProfileUpdateRequest):
    """Set the caller's own ``handle`` / ``display_name`` / ``bio``.

    Only the fields present in the body are updated (all optional). ``handle`` is
    normalised + shape-validated by the request model; a handle already claimed by
    another creator is a clean ``409`` (never a 500 on the UNIQUE constraint). All
    three are safe, public identity fields.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_creators(request_id)

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)

            if body.handle is not None:
                # Reject a handle already owned by a DIFFERENT user up-front (a
                # clean 409 rather than relying solely on the DB UNIQUE fire).
                clash = (
                    session.execute(
                        select(User).where(User.handle == body.handle).limit(1)
                    )
                    .scalars()
                    .first()
                )
                if clash is not None and clash.id != user.id:
                    raise HttpException(
                        task_id=request_id,
                        status_code=409,
                        message=f"{request_id}: handle is already taken",
                    )
                user.handle = body.handle
            if body.display_name is not None:
                user.display_name = body.display_name.strip()
            if body.bio is not None:
                user.bio = body.bio.strip()

            try:
                session.flush()
            except IntegrityError:
                # Lost a concurrent race for the same handle — surface a clean 409.
                session.rollback()
                raise HttpException(
                    task_id=request_id,
                    status_code=409,
                    message=f"{request_id}: handle is already taken",
                )

            data = creators_service.public_profile(session, user.id)
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"failed to update profile, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to update the profile",
        )

    return utils.get_response(200, data)
