"""ReelForge growth ("me") controller (Phase 7).

Per-user, auth-gated growth surfaces served under ``/api/v1`` via
:func:`app.controllers.v1.base.new_router`:

* ``GET  /me/insights``          — the caller's dashboard analytics
  (:func:`app.services.insights.user_insights`), strictly scoped to the caller.
* ``GET  /me/referral``          — the caller's referral code + lifetime stats
  (:func:`app.services.referrals.referral_stats`). The code is generated and
  persisted on first sight via ``UserRepository.set_referral_code``.
* ``POST /me/referral/redeem``   — redeem another user's code
  (:func:`app.services.referrals.redeem_referral`); self- and double-redemption
  are rejected (``400`` / ``409``), an unknown code is a ``400``.
* ``GET/POST/DELETE /me/presets`` — CRUD over the caller's saved presets, with
  ownership enforced (a user can neither read nor delete another user's preset).

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard), so the two auth paths (Clerk JWT + ``x-api-key``) and the get-or-create
  behaviour are identical to the rest of the API and this module stays import-safe.
* **Import-safe growth deps.** The persistence models/repositories authored by
  the sibling DB agent (``UserPreset`` / ``UserPresetRepository`` /
  ``UserRepository``) are imported optionally; when they are not yet present the
  module falls back to equivalent, migration-matching local definitions so the
  endpoints work today and transparently adopt the DB layer once it lands. When
  the DB layer is entirely absent every endpoint degrades to a clean ``503``.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Path, Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the canonical persistence guard + auth helpers from jobs.py (which owns
# the guarded DB import). When the DB layer is absent these are ``None`` and
# ``_require_db`` raises a clean 503 at request time.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    InsightsResponse,
    PresetDeleteResponse,
    PresetListResponse,
    PresetResponse,
    RedeemRequest,
    RedeemResponse,
    ReferralResponse,
)
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

# The provenance key the trusted server-side clone path
# (:func:`app.services.marketplace.clone_to_user`, mirroring its
# ``SOURCE_MARKETPLACE_KEY``) writes into a preset's ``config`` to record the
# marketplace listing it genuinely descends from. It MUST NOT be settable from
# caller-supplied preset config — otherwise a user could hand-craft a preset
# claiming false provenance and forge remix-tree parentage (a fake parent link /
# inflated ``remix_count``) or spoof a win-score cohort at publish time. It is
# stripped from every ``POST /me/presets`` body so only a real clone can carry it.
_RESERVED_PROVENANCE_KEY: str = "source_marketplace_id"


# --------------------------------------------------------------------------- #
# Guarded growth persistence layer (authored by the sibling DB agent; may be
# absent at compile time). Keeps this module import-safe — a missing layer
# degrades to a clean 503 at request time (via ``_require_presets``) instead of
# an ImportError at startup, mirroring the guard in ``jobs.py``.
# --------------------------------------------------------------------------- #
try:
    from app.models.db.models import UserPreset  # noqa: F401 (re-exported for tests)
    from app.models.db.repositories import (
        UserPresetRepository,
        UserRepository,
    )

    _GROWTH_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    UserPreset = None  # type: ignore[assignment,misc]
    UserPresetRepository = None  # type: ignore[assignment,misc]
    UserRepository = None  # type: ignore[assignment,misc]
    _GROWTH_IMPORT_ERROR = exc


# --------------------------------------------------------------------------- #
# Guarded workspaces service (Team Workspaces layer). SHARED BRAND KITS reuse
# its membership/authorization primitives (``require_role`` / ``get_membership``
# via ``WorkspaceRepository`` / ``list_workspaces`` / the ``ROLE_*`` ranks).
# Guarded independently so a partial environment degrades gracefully — sharing a
# preset to a workspace fails closed with a clean 503, while listing/deleting a
# purely personal preset keeps working without the service.
# --------------------------------------------------------------------------- #
try:
    from app.services import workspaces as ws_service
    from app.services.workspaces import (
        ROLE_ADMIN,
        ROLE_MEMBER,
        ROLE_RANK,
        WorkspaceRepository,
    )

    _WS_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the WS layer
    ws_service = None  # type: ignore[assignment]
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    ROLE_ADMIN = "admin"  # type: ignore[assignment]
    ROLE_MEMBER = "member"  # type: ignore[assignment]
    ROLE_RANK = {"member": 0, "admin": 1, "owner": 2}  # type: ignore[assignment]
    _WS_IMPORT_ERROR = exc


# --------------------------------------------------------------------------- #
# Guarded push-token persistence (out-of-app render push). Imported separately
# so a partial environment degrades this feature alone to a clean 503 without
# taking down presets/referrals — mirroring the guard style above.
# --------------------------------------------------------------------------- #
try:
    from app.models.db.repositories import PushTokenRepository

    _PUSH_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    PushTokenRepository = None  # type: ignore[assignment,misc]
    _PUSH_IMPORT_ERROR = exc


# --------------------------------------------------------------------------- #
# Local request body (SHARED BRAND KITS). ``schema.py`` is owned by a sibling
# agent, so the optional ``workspace_id`` — which SHARES a preset to a team — is
# accepted via this tiny local model (``extra="allow"`` keeps it forward
# compatible) rather than by editing the shared schema.
# --------------------------------------------------------------------------- #
class PresetCreateBody(BaseModel):
    """Body for ``POST /me/presets`` with an optional shared ``workspace_id``."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(default="", max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    workspace_id: Optional[str] = None


class PushTokenRegisterBody(BaseModel):
    """Body for ``POST /me/push-tokens`` (mobile push registration).

    Matches the mobile client's payload exactly
    (``lib/api.ts::registerPushToken``): the Expo push token, the device
    platform, and the stable SecureStore install id used as the UPSERT key. The
    ``expo_token`` is SENSITIVE and is never logged. Bounds mirror the DB column
    limits so an oversized value fails validation rather than at the DB.
    """

    expo_token: str = Field(..., min_length=1, max_length=512)
    platform: str = Field(default="", max_length=16)
    install_id: str = Field(..., min_length=1, max_length=64)


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _preset_public_data(preset: Any) -> dict:
    """Serialise a ``UserPreset`` row to its public, JSON-safe envelope.

    Includes the sharing metadata: ``workspace_id`` (the team the preset is
    shared to, or ``None`` when private) and a derived ``shared`` boolean, so a
    client can distinguish a personal brand kit from a team-shared one.
    """
    created_at = getattr(preset, "created_at", None)
    workspace_id = getattr(preset, "workspace_id", None)
    return {
        "id": preset.id,
        "name": preset.name,
        "config": dict(preset.config or {}),
        "workspace_id": workspace_id,
        "shared": workspace_id is not None,
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


# --------------------------------------------------------------------------- #
# Insights
# --------------------------------------------------------------------------- #
@router.get(
    "/me/insights",
    response_model=InsightsResponse,
    summary="Current user's dashboard insights",
)
def me_insights(request: Request):
    """Return the authenticated caller's analytics (strictly caller-scoped)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)

    try:
        from app.services.insights import user_insights
    except Exception as exc:  # noqa: BLE001 - insights service optional at import
        logger.error(f"insights service unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: insights service is not available",
        )

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = user_insights(session, user.id)
        except Exception as exc:  # noqa: BLE001 - aggregation failure -> 502
            logger.error(
                f"user_insights failed for {user.id}, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to compute insights",
            )
    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# Referral
# --------------------------------------------------------------------------- #
@router.get(
    "/me/referral",
    response_model=ReferralResponse,
    summary="Current user's referral code and stats",
)
def me_referral(request: Request):
    """Return the caller's referral code + stats, persisting the code on first sight."""
    request_id = base.get_task_id(request)
    _require_db(request_id)

    try:
        from app.services import referrals
    except Exception as exc:  # noqa: BLE001 - referrals service optional at import
        logger.error(f"referrals service unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: referrals service is not available",
        )

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        # Generate + persist the user's canonical code on first call. Persistence
        # is best-effort (the code is deterministic), so a persistence hiccup must
        # never fail the read.
        try:
            code = referrals.code_for_user(session, user.id)
            UserRepository(session).set_referral_code(user.id, code)
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            logger.warning(
                f"referral code persistence skipped for {user.id}, "
                f"request_id: {request_id}: {exc}"
            )
        try:
            data = referrals.referral_stats(session, user.id)
        except Exception as exc:  # noqa: BLE001 - stats failure -> 502
            logger.error(
                f"referral_stats failed for {user.id}, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to compute referral stats",
            )
    return utils.get_response(200, data)


# Per-caller cap on redemption attempts. A legitimate user redeems at most
# once ever (the ledger enforces that), so this only bounds retries after a
# typo'd code — while also bounding how many times an abusive caller can
# trigger the full-user-table scan fallback in
# ``app.services.referrals._find_referrer_id`` per hour.
_REDEEM_RATE_LIMIT: int = 10
_REDEEM_RATE_WINDOW_S: int = 3600

# HTTP status per guarded ``redeem_referral`` error slug.
_REDEEM_ERROR_STATUS: dict[str, int] = {
    "invalid_input": 400,
    "invalid_code": 400,
    "self_referral": 400,
    "already_redeemed": 409,
}


@router.post(
    "/me/referral/redeem",
    response_model=RedeemResponse,
    summary="Redeem a referral code",
)
def me_referral_redeem(request: Request, body: RedeemRequest):
    """Redeem ``code`` for the caller, granting both parties on success.

    Guarded failures map to a clean HTTP error: an unknown/invalid or
    self-referral code is a ``400``; a double-redemption is a ``409``.

    Rate-limited per caller (see ``_REDEEM_RATE_LIMIT`` /
    ``_REDEEM_RATE_WINDOW_S``): unlike most redeems this endpoint grants real
    credits, and an unrecognized code falls through to
    :func:`app.services.referrals._find_referrer_id`'s full-user-table scan
    fallback, so an unbounded stream of guesses from one caller is both an
    abuse vector and a cost/DoS vector, not just wasted requests.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)

    code = str(getattr(body, "code", "") or "").strip()
    if not code:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: referral code is required",
        )

    try:
        from app.services.referrals import redeem_referral
    except Exception as exc:  # noqa: BLE001 - referrals service optional at import
        logger.error(f"referrals service unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: referrals service is not available",
        )

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        enforce_rate_limit(
            request,
            f"referral_redeem:{user.id}",
            limit=_REDEEM_RATE_LIMIT,
            window_s=_REDEEM_RATE_WINDOW_S,
        )
        try:
            result = redeem_referral(session, user.id, code)
        except Exception as exc:  # noqa: BLE001 - unexpected grant failure -> 502
            logger.error(
                f"redeem_referral failed for {user.id}, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to redeem referral code",
            )

        if not result.get("ok"):
            slug = str(result.get("error") or "invalid_code")
            status = _REDEEM_ERROR_STATUS.get(slug, 400)
            raise HttpException(
                task_id=request_id,
                status_code=status,
                message=f"{request_id}: {result.get('message') or slug}",
            )
    # Tell the inviter their referral paid out (after the grants committed).
    try:
        from app.services.notifications import notify_referral_earned

        notify_referral_earned(
            str(result.get("referrer_id") or ""), int(result.get("referrer_grant") or 0)
        )
    except Exception as exc:  # noqa: BLE001 - a notification must never fail the redeem
        logger.warning(f"referral notification failed, request_id: {request_id}: {exc}")
    return utils.get_response(200, result)


# --------------------------------------------------------------------------- #
# Saved presets (ownership enforced end-to-end)
# --------------------------------------------------------------------------- #
def _require_presets(request_id: str) -> None:
    """Raise 503 when the preset persistence model is unavailable."""
    if _GROWTH_IMPORT_ERROR is not None or UserPreset is None:
        logger.error(
            f"preset persistence unavailable, request_id: {request_id}, "
            f"error: {_GROWTH_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: preset storage is not available",
        )


def _require_workspaces(request_id: str) -> None:
    """Raise 503 when the workspaces service (sharing layer) is unavailable.

    Only the *sharing* paths (sharing a preset to a team, an admin deleting a
    teammate's shared preset) require the workspaces service; personal preset
    reads/writes stay available without it.
    """
    if _WS_IMPORT_ERROR is not None or ws_service is None:
        logger.error(
            f"workspaces service unavailable, request_id: {request_id}, "
            f"error: {_WS_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: workspaces service is not available",
        )


def _caller_workspace_ids(session: Any, user_id: str) -> list[str]:
    """Return the ids of every workspace ``user_id`` is a member of.

    Degrades to an empty list (own-presets-only) when the workspaces service is
    absent, so listing never fails just because the sharing layer is missing.
    """
    if _WS_IMPORT_ERROR is not None or ws_service is None:
        return []
    try:
        workspaces = ws_service.list_workspaces(session, user_id)
    except Exception as exc:  # noqa: BLE001 - never fail a read on the sharing layer
        logger.warning(
            f"listing caller workspaces skipped for {user_id}: {exc}"
        )
        return []
    return [ws.id for ws in workspaces if getattr(ws, "id", None)]


@router.get(
    "/me/presets",
    response_model=PresetListResponse,
    summary="List the caller's saved presets (own + shared to their workspaces)",
)
def me_list_presets(request: Request):
    """Return the caller's own presets UNION presets shared to their workspaces.

    The result is the caller's own brand kits (private *and* the ones they
    shared) plus every preset any teammate shared to a workspace the caller is a
    member of — de-duplicated and newest first. Each item carries its
    ``workspace_id`` and a ``shared`` flag so a shared team kit is
    distinguishable from a personal one.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_presets(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        workspace_ids = _caller_workspace_ids(session, user.id)
        presets = UserPresetRepository(session).list_for_user_and_workspaces(
            user.id, workspace_ids
        )
        data = [_preset_public_data(p) for p in presets]
    return utils.get_response(200, data)


@router.post(
    "/me/presets",
    response_model=PresetResponse,
    summary="Create a saved preset (optionally shared to a workspace)",
)
def me_create_preset(request: Request, body: PresetCreateBody):
    """Create a named preset ({name, config}) owned by the caller.

    When ``workspace_id`` is supplied the preset is SHARED to that workspace so
    every member sees it; the caller must be a member of the workspace (``403``
    otherwise). Omitting ``workspace_id`` keeps the preset private to the caller.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_presets(request_id)

    name = str(getattr(body, "name", "") or "").strip()
    if not name:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: preset name is required",
        )
    config = getattr(body, "config", None) or {}
    if not isinstance(config, dict):
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: preset config must be an object",
        )
    # Never let a caller inject the server-only provenance key (see
    # ``_RESERVED_PROVENANCE_KEY``): build a fresh, sanitized config so a
    # hand-crafted preset can never forge remix-tree parentage. Immutable — the
    # input dict is not mutated.
    config = {k: v for k, v in config.items() if k != _RESERVED_PROVENANCE_KEY}
    workspace_id = getattr(body, "workspace_id", None)
    if workspace_id is not None:
        workspace_id = str(workspace_id).strip() or None

    # Sharing a preset to a workspace requires the sharing layer + membership.
    if workspace_id is not None:
        _require_workspaces(request_id)

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            if workspace_id is not None:
                # Membership is the single share gate: a non-member (or an
                # unknown workspace) raises ``PermissionError`` -> 403 and no
                # preset is created.
                try:
                    ws_service.require_role(
                        session, workspace_id, user.id, ROLE_MEMBER
                    )
                except PermissionError:
                    raise HttpException(
                        task_id=request_id,
                        status_code=403,
                        message=(
                            f"{request_id}: you are not a member of this workspace"
                        ),
                    )
            preset = UserPresetRepository(session).create(
                user.id, name, config, workspace_id=workspace_id
            )
            data = _preset_public_data(preset)
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"create preset failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to save preset",
        )
    return utils.get_response(200, data)


@router.delete(
    "/me/presets/{preset_id}",
    response_model=PresetDeleteResponse,
    summary="Delete a saved preset",
)
def me_delete_preset(
    request: Request,
    preset_id: str = Path(..., description="Preset ID"),
):
    """Delete a preset.

    Authorization:

    * A **personal** preset (no ``workspace_id``) is creator-only — a foreign or
      unknown id is a ``404`` (indistinguishable, so a guessed id can never
      confirm another user's preset).
    * A **workspace-shared** preset can be deleted by its creator OR a workspace
      ``admin``+. A member of the workspace who is neither gets a ``403`` (they
      can see it via ``GET /me/presets`` but may not delete it); a non-member
      gets a ``404`` (no existence leak).
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_presets(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        preset = session.get(UserPreset, preset_id)

        # Missing, or a private preset owned by someone else -> 404 (no leak).
        if preset is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: preset not found",
            )

        is_creator = preset.user_id == user.id
        shared_workspace_id = getattr(preset, "workspace_id", None)

        if not is_creator:
            # Only shared presets are ever deletable by a non-creator.
            if not shared_workspace_id:
                raise HttpException(
                    task_id=request_id,
                    status_code=404,
                    message=f"{request_id}: preset not found",
                )
            _require_workspaces(request_id)
            try:
                membership = ws_service.require_role(
                    session, shared_workspace_id, user.id, ROLE_MEMBER
                )
            except PermissionError:
                # Not a member of the sharing workspace -> cannot even see it.
                raise HttpException(
                    task_id=request_id,
                    status_code=404,
                    message=f"{request_id}: preset not found",
                )
            # Visible to this member, but only admin+ may delete a teammate's kit.
            if ROLE_RANK.get(membership.role, -1) < ROLE_RANK[ROLE_ADMIN]:
                raise HttpException(
                    task_id=request_id,
                    status_code=403,
                    message=(
                        f"{request_id}: only the preset's creator or a workspace "
                        f"admin can delete a shared preset"
                    ),
                )

        # Authorized (creator, or workspace admin+ of a shared preset). The row
        # is already loaded, so delete it directly within this transaction.
        session.delete(preset)
        session.flush()
    return utils.get_response(200, {"deleted": True, "id": preset_id})


# --------------------------------------------------------------------------- #
# Push tokens (out-of-app render notifications)
# --------------------------------------------------------------------------- #
# Valid Expo push token prefixes; a value not matching one of these is rejected
# before it ever reaches the DB (and is never logged).
_EXPO_TOKEN_PREFIXES: tuple[str, ...] = ("ExponentPushToken[", "ExpoPushToken[")
# Delivery channels the mobile client registers.
_PUSH_PLATFORMS: frozenset[str] = frozenset({"ios", "android"})


def _require_push_tokens(request_id: str) -> None:
    """Raise 503 when the push-token persistence layer is unavailable."""
    if _PUSH_IMPORT_ERROR is not None or PushTokenRepository is None:
        logger.error(
            f"push-token persistence unavailable, request_id: {request_id}, "
            f"error: {_PUSH_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: push registration is not available",
        )


@router.post(
    "/me/push-tokens",
    summary="Register (upsert) this install's Expo push token",
)
def register_push_token(request: Request, body: PushTokenRegisterBody):
    """UPSERT the caller's Expo push token for this install.

    Mirrors the mobile client's call (``POST /me/push-tokens`` with
    ``{expo_token, platform, install_id}``, authed via ``x-api-key``). The token
    is stored keyed by the stable ``install_id`` so re-registration (a rotated
    token, a re-signed-in user) refreshes the single row for this device rather
    than piling up duplicates, and the caller is recorded as the owner so the
    job-completion path can reach every one of their devices.

    The Expo token is SENSITIVE: it is validated for shape, persisted, and never
    logged. A malformed token or platform is a ``400``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_push_tokens(request_id)

    expo_token = str(getattr(body, "expo_token", "") or "").strip()
    if not expo_token.startswith(_EXPO_TOKEN_PREFIXES):
        # Never echo the token back in the error (sensitive) — describe the shape.
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: a valid Expo push token is required",
        )

    platform = str(getattr(body, "platform", "") or "").strip().lower()
    if platform and platform not in _PUSH_PLATFORMS:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: platform must be one of {sorted(_PUSH_PLATFORMS)}",
        )

    install_id = str(getattr(body, "install_id", "") or "").strip()
    if not install_id:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: install_id is required",
        )

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            PushTokenRepository(session).upsert(
                install_id=install_id,
                token=expo_token,
                platform=platform,
                user_id=user.id,
            )
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502 (no token in log)
        logger.error(f"push token upsert failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to register push token",
        )
    return utils.get_response(200, {"registered": True})


@router.delete(
    "/me/push-tokens/{install_id}",
    summary="Invalidate this install's push token",
)
def delete_push_token(
    request: Request,
    install_id: str = Path(..., description="Install ID"),
):
    """Invalidate the caller's push token for one install (owner-scoped).

    Flips the install's row ``is_active=False`` so it drops out of every future
    send (e.g. on sign-out or when the user disables notifications). A missing or
    foreign install id is a ``404`` (indistinguishable, so a guessed id can never
    confirm another user's token). Invalidating an already-inactive token is an
    idempotent success.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_push_tokens(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        invalidated = PushTokenRepository(session).deactivate_for_install(
            install_id, user.id
        )
        if not invalidated:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: push token not found",
            )
    return utils.get_response(200, {"deleted": True, "install_id": install_id})
