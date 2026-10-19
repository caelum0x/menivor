"""Public Watermarked Share Pages — create / view / revoke share links.

A creator turns one of THEIR OWN completed reels into a public, unguessable,
revocable share link; anyone (no auth) who has the link sees a page rendering the
reel's WATERMARKED preview (never the clean output/``result_key``), its title, and
a soft call-to-action. Views are counted for social proof, and signup attribution
is handled by the frontend via the sharer's referral code (exposed safely here).

A thin, validation layer over :class:`~app.models.db.repositories.ShareLinkRepository`.
Controllers depend on this service rather than touching the repository directly,
mirroring :mod:`app.services.hook_performance` and :mod:`app.services.marketplace`.

Design invariants
-----------------
* **Strictly per-user creation.** :func:`create_share` verifies the job belongs to
  the caller BEFORE any write (raising ``PermissionError`` otherwise), exactly like
  :func:`app.services.hook_performance.log_performance`. There is no cross-user
  write path.
* **Safe public surface.** :func:`public_view` returns ONLY safe fields
  (:data:`SAFE_PUBLIC_FIELDS`): the reel's title, a presigned GET of the
  WATERMARKED preview/poster/cover asset, the reel's ``created_at`` and the
  sharer's referral code. It NEVER returns the clean ``result_key``, the owning
  ``user_id``, or any private financials (credits, cost, revenue).
* **Revoked == gone.** A revoked link resolves to nothing on the public read path,
  so :func:`public_view` raises ``LookupError`` (a 404 at the API) and never
  increments a view for a link that has been taken offline.
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger
from sqlalchemy.orm import Session

from app.models.db.models import Job, ShareLink
from app.models.db.repositories import ShareLinkRepository
from app.services.referrals import code_for_user

#: The EXACT set of keys the public share DTO exposes. Every one is safe to serve
#: to an unauthenticated visitor; the clean ``result_key``, the owning ``user_id``
#: and any private financials are deliberately absent.
SAFE_PUBLIC_FIELDS: tuple[str, ...] = (
    "title",
    "watermarked_preview_url",
    "created_at",
    "sharer_referral_code",
)

#: M3.3 (WP3.3): the text burned into free exports (the preview clip that free
#: users and public share pages see). ``MENIVOR_FREE_WATERMARK=off`` turns it off;
#: paid users download the clean MP4, which never carries it.
FREE_WATERMARK_ENV: str = "MENIVOR_FREE_WATERMARK"
FREE_WATERMARK_TEXT: str = "Made with Menivor"


def free_watermark_text(env: dict[str, str] | None = None) -> str:
    """The free-export watermark text, or ``""`` when the flag turns it off."""
    import os

    source = os.environ if env is None else env
    raw = str(source.get(FREE_WATERMARK_ENV, "") or "").strip().lower()
    return "" if raw in {"0", "false", "no", "off"} else FREE_WATERMARK_TEXT


#: ``Job.params`` keys probed (in priority order) for a human title to show on the
#: public page. Falls back to the hook subject line, then an empty string.
_TITLE_KEYS: tuple[str, ...] = ("title", "video_subject", "subject")

#: Type of the presign seam :func:`public_view` uses to turn a safe R2 key into a
#: time-limited GET URL. Injectable so tests stay hermetic (no boto3/network) and
#: so the watermarked-preview source can be swapped without touching this module.
Presigner = Callable[[str], str]


def _default_presign(key: str) -> str:
    """Presign a GET URL for ``key`` via the process-wide R2 client.

    Imported lazily so merely importing this module never requires boto3 or a
    populated ``config.r2`` section.
    """
    from app.services.storage.r2 import get_r2_client

    return get_r2_client().presign_get(key)


def _safe_preview_key(job: Job) -> str:
    """Return the WATERMARKED preview asset key to expose, or ``""``.

    Prefers the low-res preview clip, then the poster/thumbnail frame, then the
    generated cover — all safe, derived/watermarked artifacts. The clean
    ``result_key`` is NEVER considered, so the public page can never leak the
    un-watermarked master render.
    """
    for attr in ("preview_key", "poster_key", "cover_key"):
        value = str(getattr(job, attr, "") or "").strip()
        if value:
            return value
    return ""


def _title_of(job: Job) -> str:
    """Best-effort human title for the reel from its ``params`` (safe fields only)."""
    params = job.params if isinstance(job.params, dict) else {}
    for key in _TITLE_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def create_share(session: Session, user_id: str, job_id: str) -> ShareLink:
    """Create (or return the existing active) public share link for the caller's reel.

    Ownership is verified BEFORE any write by the repository: the job must belong
    to ``user_id`` or a ``PermissionError`` is raised (mirroring
    :func:`app.services.hook_performance.log_performance`). One active link exists
    per job — calling this again for the same job returns the same live link rather
    than minting a duplicate.

    Args:
        session: An active SQLAlchemy session (the caller owns the transaction).
        user_id: The creator sharing their own reel (the resolved caller).
        job_id: The creator's own job whose reel is being shared.

    Returns:
        The :class:`ShareLink` row (carrying the unguessable ``token``) so the
        caller can build the public URL.

    Raises:
        ValueError: If ``user_id`` / ``job_id`` is blank, or the job does not
            exist.
        PermissionError: If the job exists but belongs to a different user.
    """
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id is required")
    if not job_id or not str(job_id).strip():
        raise ValueError("job_id is required")

    link = ShareLinkRepository(session).create_for_job(
        job_id=str(job_id).strip(), user_id=str(user_id).strip()
    )
    logger.info(
        f"share link ready: token={link.token[:6]}… "
        f"(job={link.job_id}, user={link.user_id})"
    )
    return link


def public_view(
    session: Session, token: str, *, presign: Presigner | None = None
) -> dict[str, Any]:
    """Resolve a public token to a SAFE view DTO and count the view.

    The token must resolve to a LIVE (non-revoked) link whose job still exists; a
    revoked/unknown token raises ``LookupError`` (a 404 at the API) and never
    increments a view. On success the link's ``view_count`` is bumped in place and
    a DTO containing ONLY :data:`SAFE_PUBLIC_FIELDS` is returned — the clean
    ``result_key``, the owning ``user_id`` and every private financial are
    deliberately absent.

    Args:
        session: An active SQLAlchemy session (the caller owns the transaction).
        token: The unguessable public share token.
        presign: Optional seam turning a safe R2 key into a presigned GET URL
            (defaults to the R2 client). Injectable so tests stay hermetic and the
            watermarked-preview source can be swapped without touching callers.

    Returns:
        ``{"title", "watermarked_preview_url", "created_at",
        "sharer_referral_code"}`` — the exact safe public field set.

    Raises:
        LookupError: If the token is unknown or the link has been revoked (or its
            job no longer exists).
    """
    repo = ShareLinkRepository(session)
    link = repo.get_by_token((token or "").strip())
    if link is None:
        raise LookupError("share link not found")

    job = session.get(Job, link.job_id)
    if job is None:
        # A dangling link (job deleted) is treated as gone rather than 500ing.
        raise LookupError("share link not found")
    # MN5: a video soft-blocked after a content report is not shown publicly.
    from app.domains.compliance.takedown import is_blocked

    if is_blocked(str(job.id)):
        raise LookupError("share link not found")

    # Count the view first so a presign hiccup never silently drops the metric.
    repo.increment_view(link.token)

    presigner = presign or _default_presign
    preview_key = _safe_preview_key(job)
    preview_url = presigner(preview_key) if preview_key else ""

    created_at = getattr(job, "created_at", None)
    return {
        "title": _title_of(job),
        "watermarked_preview_url": preview_url,
        # ISO-8601 string keeps the DTO JSON-clean across SQLite/Postgres.
        "created_at": created_at.isoformat() if created_at is not None else None,
        # Safe, public referral handle powering frontend signup attribution.
        "sharer_referral_code": code_for_user(session, link.user_id),
    }


def revoke_share(session: Session, user_id: str, token: str) -> bool:
    """Owner-scoped revoke of a share link; return whether a live link was revoked.

    Delegates to the repository's guarded, owner-scoped UPDATE: returns ``True``
    only when a live link belonging to ``user_id`` was flipped to revoked. Returns
    ``False`` when the token is unknown, belongs to a different user, or is already
    revoked — so a caller can never revoke another creator's link by guessing its
    token, and a double-revoke is a harmless no-op. A blank ``user_id`` / ``token``
    is a no-op ``False``.

    Args:
        session: An active SQLAlchemy session (the caller owns the transaction).
        user_id: The creator revoking their own share link (the resolved caller).
        token: The share token to revoke.

    Returns:
        ``True`` if a live link was revoked, ``False`` otherwise.
    """
    return ShareLinkRepository(session).revoke(
        token=(token or "").strip(), user_id=(user_id or "").strip()
    )


__all__ = [
    "SAFE_PUBLIC_FIELDS",
    "create_share",
    "public_view",
    "revoke_share",
]
