"""In-app notification emit layer — the counterpart to the external webhook.

Where :mod:`app.services.webhooks` POSTs a job's completion to a user-registered
callback URL, this module writes an in-app :class:`~app.models.db.models.Notification`
row that the client renders as a bell + unread badge + notification center.

The server best-effort emits on four events:

* ``job_complete``    — a render job reached ``done`` (with ``job_id`` + result),
* ``job_failed``      — a render job reached ``failed`` (with the ``error``),
* ``low_credits``     — a user's balance dropped below a threshold,
* ``referral_earned`` — a user earned credits from a referral.

Design rules
------------
* **Best-effort (CRITICAL).** Emitting a notification must NEVER fail the caller.
  Every public function opens its own short-lived DB session and swallows *all*
  errors (logging them), returning the new notification id on success or
  ``None`` on any failure. A notification write failing must never abort a job,
  a credit grant, or a referral redemption.
* **Pure emit layer.** This module owns no schema and no HTTP — it only composes
  a human-readable ``title``/``body`` plus an opaque ``data`` dict and delegates
  the INSERT to :class:`NotificationRepository`. Persistence-layer imports are
  guarded so merely importing this module never crashes a stripped-down
  environment where the DB layer is absent.
* **No secrets.** ``data`` carries only non-sensitive event metadata (job ids,
  balances, amounts) — never API keys, presigned credentials, or raw errors that
  might leak internals beyond the already-surfaced job error string.
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

# --------------------------------------------------------------------------- #
# Guarded persistence-layer imports
#
# Importing this module must never crash when the DB layer is unavailable (e.g.
# a stripped-down worker image or a ``py_compile`` sanity check). When the
# imports fail the emit functions degrade to a logged no-op that returns
# ``None`` — consistent with the best-effort contract. Both names are bound at
# module scope so tests can monkeypatch them.
# --------------------------------------------------------------------------- #
try:  # pragma: no cover - exercised indirectly; failure path is defensive
    from app.models.db import get_session
    from app.models.db.repositories import NotificationRepository
except Exception as _exc:  # pragma: no cover - only when the DB layer is absent
    get_session = None  # type: ignore[assignment]
    NotificationRepository = None  # type: ignore[assignment]
    logger.warning(f"notifications persistence layer unavailable: {_exc}")

# Out-of-app push delivery (Expo). Imported behind a guard and bound at module
# scope (so tests can monkeypatch it): emitting a render-lifecycle notification
# also fires a native push to the user's registered devices — reusing this one
# emit layer rather than duplicating the trigger at every call site. The push
# module is itself fully best-effort, so a push failure can never disturb the
# in-app write or the caller.
try:  # pragma: no cover - exercised indirectly; failure path is defensive
    from app.services import push as _push
except Exception as _push_exc:  # pragma: no cover - only when the push layer is absent
    _push = None  # type: ignore[assignment]
    logger.warning(f"push delivery layer unavailable: {_push_exc}")

# Job lifecycle states. Guarded so this module imports even without app config;
# the fallbacks mirror ``app/models/const.py`` (COMPLETE=1, FAILED=-1).
try:
    from app.models import const

    _STATE_COMPLETE: int = const.TASK_STATE_COMPLETE
    _STATE_FAILED: int = const.TASK_STATE_FAILED
except Exception:  # pragma: no cover - defensive; const has no heavy deps
    _STATE_COMPLETE = 1
    _STATE_FAILED = -1


# --------------------------------------------------------------------------- #
# Notification kinds (contract-stable strings persisted in ``Notification.kind``)
# --------------------------------------------------------------------------- #
KIND_JOB_COMPLETE: str = "job_complete"
KIND_JOB_FAILED: str = "job_failed"
KIND_LOW_CREDITS: str = "low_credits"
KIND_REFERRAL_EARNED: str = "referral_earned"
KIND_PUBLISH_COMPLETE: str = "publish_complete"
KIND_PUBLISH_FAILED: str = "publish_failed"
KIND_RENDER_COMPLETE: str = "render_complete"
KIND_RENDER_FAILED: str = "render_failed"
KIND_FILM_EXPORT_COMPLETE: str = "film_export_complete"
KIND_FILM_EXPORT_FAILED: str = "film_export_failed"
KIND_WORKSPACE_INVITE: str = "workspace_invite"

#: Default balance at/below which a ``low_credits`` nudge is emitted.
DEFAULT_LOW_CREDITS_THRESHOLD: int = 3


# --------------------------------------------------------------------------- #
# Internal best-effort writer
# --------------------------------------------------------------------------- #
def _emit(
    user_id: str,
    kind: str,
    title: str,
    body: str = "",
    data: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Persist one notification, swallowing every error (best-effort).

    Opens a short-lived session via :func:`get_session`, delegates the INSERT to
    :class:`NotificationRepository`, and returns the new notification id on
    success. Returns ``None`` — never raises — when ``user_id`` is empty, the
    persistence layer is unavailable, or the write fails for any reason, so a
    notification failure can never propagate into (and abort) the caller.
    """
    if not user_id:
        logger.warning(f"notification emit skipped: empty user_id (kind={kind})")
        return None

    if get_session is None or NotificationRepository is None:
        logger.warning(
            f"notification emit skipped: persistence unavailable (kind={kind})"
        )
        return None

    try:
        with get_session() as session:
            notification = NotificationRepository(session).create(
                user_id=user_id,
                kind=kind,
                title=title,
                body=body,
                data=dict(data or {}),
            )
            # Read the id inside the transaction (create() flushes to populate
            # it) so the value is available regardless of expire-on-commit.
            return notification.id
    except Exception as exc:
        logger.warning(
            f"notification emit failed (kind={kind}, user={user_id}): {exc}"
        )
        return None


# --------------------------------------------------------------------------- #
# Best-effort out-of-app push (never raises)
# --------------------------------------------------------------------------- #
def _safe_push(kind: str, user_id: str, job_id: str) -> None:
    """Fire the matching Expo push for a render-lifecycle event (best-effort).

    Fully swallowed: the push module is already best-effort, but this extra guard
    guarantees a push (or a missing push layer) can never disturb the in-app
    notification write or the caller. Only render-lifecycle kinds push; growth
    nudges (``low_credits`` / ``referral_earned``) stay in-app only.
    """
    if _push is None or not user_id:
        return
    try:
        if kind == KIND_JOB_COMPLETE:
            _push.send_job_complete(user_id, job_id)
        elif kind == KIND_JOB_FAILED:
            _push.send_job_failed(user_id, job_id)
    except Exception as exc:  # noqa: BLE001 - push must never disturb the emit path
        logger.warning(f"push dispatch failed (kind={kind}, user={user_id}): {exc}")


# --------------------------------------------------------------------------- #
# Public emitters
# --------------------------------------------------------------------------- #
_COMPLETE_COPY: dict[str, tuple[str, str]] = {
    "broll_gen": ("Your B-roll clip is ready", "Your AI B-roll clip has finished generating."),
    "speak_lipsync": ("Your talking video is ready", "Your lipsync video has finished rendering."),
    "character_lora": ("Your character is trained", "Your character model finished training and is ready to use."),
    "clipping": ("Your clips are ready", "Your long video was cut into short clips."),
    "editor_export": ("Your export is ready", "Your edited video has finished exporting."),
    "editor_timeline_export": ("Your export is ready", "Your edited video has finished exporting."),
}


def notify_job_complete(
    user_id: str,
    job_id: str,
    result_url: Optional[str] = None,
    kind: str = "",
) -> Optional[str]:
    """Emit a ``job_complete`` notification for a finished render.

    ``result_url`` (when supplied) is a ready-to-open link to the finished reel;
    it is included in ``data`` only when truthy so an absent link never leaves a
    dangling empty key.
    """
    data: dict[str, Any] = {"job_id": job_id}
    if result_url:
        data["result_url"] = result_url
    title, body = _COMPLETE_COPY.get(
        str(kind or ""),
        ("Your video is ready", "Your reel has finished rendering and is ready to view."),
    )
    if kind:
        data["kind"] = str(kind)
    notification_id = _emit(
        user_id,
        KIND_JOB_COMPLETE,
        title=title,
        body=body,
        data=data,
    )
    # Also reach backgrounded devices via a native push (best-effort). Fired
    # independently of the in-app write so a push lands even if that write failed.
    _safe_push(KIND_JOB_COMPLETE, user_id, job_id)
    # A reel (the default kind) also emails "your reels are ready": once per
    # run, on its first finished reel, so a creator who closed the tab comes
    # back. Deduplicated and best-effort inside job_emails.
    if str(kind or "") in ("", REEL_JOB_KIND):
        _safe_ready_email(job_id)
    return notification_id


REEL_JOB_KIND = "avatar_reel"


def _safe_ready_email(job_id: str) -> None:
    try:
        from app.services.job_emails import send_reels_ready_email

        send_reels_ready_email(job_id)
    except Exception as exc:  # noqa: BLE001 - an email must never disturb the caller
        logger.warning(f"ready email dispatch failed (job={job_id}): {exc}")


def notify_job_failed(
    user_id: str,
    job_id: str,
    error: str,
) -> Optional[str]:
    """Emit a ``job_failed`` notification carrying the failure reason."""
    message = str(error or "").strip() or "unknown error"
    notification_id = _emit(
        user_id,
        KIND_JOB_FAILED,
        title="Your video failed to render",
        body=f"Something went wrong while rendering your reel: {message}",
        data={"job_id": job_id, "error": message},
    )
    # Also reach backgrounded devices via a native push (best-effort). The push
    # body is generic (no raw error) so nothing internal leaks to the lock screen.
    _safe_push(KIND_JOB_FAILED, user_id, job_id)
    return notification_id


def notify_low_credits(
    user_id: str,
    balance: int,
    threshold: int = DEFAULT_LOW_CREDITS_THRESHOLD,
) -> Optional[str]:
    """Emit a ``low_credits`` nudge when a user's balance runs low."""
    safe_balance = int(balance or 0)
    return _emit(
        user_id,
        KIND_LOW_CREDITS,
        title="You're running low on credits",
        body=(
            f"You have {safe_balance} credit(s) left. "
            "Top up to keep creating reels."
        ),
        data={"balance": safe_balance, "threshold": int(threshold)},
    )


def notify_referral_earned(
    user_id: str,
    credits: int,
) -> Optional[str]:
    """Emit a ``referral_earned`` notification when a referral pays out."""
    earned = int(credits or 0)
    return _emit(
        user_id,
        KIND_REFERRAL_EARNED,
        title="You earned referral credits",
        body=(
            f"You just earned {earned} credit(s) from a referral. "
            "Thanks for sharing!"
        ),
        data={"credits": earned},
    )


def notify_publish_complete(
    user_id: str,
    job_id: str,
    platforms: list[str],
    urls: Optional[list[str]] = None,
) -> Optional[str]:
    """Emit a ``publish_complete`` notification once a post is live."""
    names = ", ".join(str(p) for p in platforms if p) or "your channels"
    data: dict[str, Any] = {"job_id": job_id, "platforms": list(platforms)}
    live_urls = [u for u in (urls or []) if u]
    if live_urls:
        data["urls"] = live_urls
    return _emit(
        user_id,
        KIND_PUBLISH_COMPLETE,
        title="Your reel is live",
        body=f"Your reel was published to {names}.",
        data=data,
    )


def notify_publish_failed(
    user_id: str,
    job_id: str,
    error: str,
) -> Optional[str]:
    """Emit a ``publish_failed`` notification carrying a sanitised reason."""
    message = str(error or "").strip() or "unknown error"
    return _emit(
        user_id,
        KIND_PUBLISH_FAILED,
        title="Your reel could not be published",
        body=f"Publishing failed: {message}",
        data={"job_id": job_id, "error": message},
    )


# --------------------------------------------------------------------------- #
# Async-GPU render + film + workspace emitters
# --------------------------------------------------------------------------- #
def _safe_push_payload(user_id: str, title: str, body: str, data: dict[str, Any]) -> None:
    """Best-effort native push with an explicit payload (never raises)."""
    if _push is None or not user_id:
        return
    try:
        _push.send_to_user(user_id, title=title, body=body, data=data)
    except Exception as exc:  # noqa: BLE001 - push must never disturb the caller
        logger.warning(f"push dispatch failed (user={user_id}): {exc}")


def notify_render_complete(
    user_id: str,
    render_job_id: str,
    *,
    source: str = "render",
    label: str = "",
    film_project_id: str = "",
) -> Optional[str]:
    """A GPU render (studio render or a film shot) reached ``COMPLETED``."""
    data: dict[str, Any] = {"render_job_id": render_job_id, "source": source or "render"}
    if film_project_id:
        data["film_project_id"] = film_project_id
    if source == "film":
        title, body = "A film shot finished rendering", (
            f"Shot render for {label or 'your film'} is done."
        )
    else:
        title, body = "Your render is ready", (
            f"{label[:120]} finished rendering." if label else "Your GPU render finished."
        )
    notification_id = _emit(user_id, KIND_RENDER_COMPLETE, title=title, body=body, data=data)
    _safe_push_payload(user_id, title, body, {**data, "type": KIND_RENDER_COMPLETE})
    return notification_id


def notify_render_failed(
    user_id: str,
    render_job_id: str,
    error: str,
    *,
    source: str = "render",
    film_project_id: str = "",
) -> Optional[str]:
    """A GPU render failed or was cancelled by the backend (hold refunded)."""
    message = str(error or "").strip() or "render failed"
    data: dict[str, Any] = {
        "render_job_id": render_job_id, "source": source or "render", "error": message,
    }
    if film_project_id:
        data["film_project_id"] = film_project_id
    title = "A film shot failed to render" if source == "film" else "Your render failed"
    body = f"{message}. Your credits for this render were refunded."
    notification_id = _emit(user_id, KIND_RENDER_FAILED, title=title, body=body, data=data)
    _safe_push_payload(
        user_id, title, "Your credits for this render were refunded.",
        {"render_job_id": render_job_id, "type": KIND_RENDER_FAILED},
    )
    return notification_id


def notify_film_export(
    user_id: str,
    project_id: str,
    *,
    ok: bool,
    title: str = "",
    error: str = "",
) -> Optional[str]:
    """The stitched final export of a film finished (or failed)."""
    name = (title or "Your film").strip()[:120]
    if ok:
        kind = KIND_FILM_EXPORT_COMPLETE
        head, body = "Your film is ready", f"{name} was stitched into a final video."
        data: dict[str, Any] = {"film_project_id": project_id}
    else:
        kind = KIND_FILM_EXPORT_FAILED
        message = str(error or "").strip() or "export failed"
        head, body = "Your film export failed", f"{name}: {message}"
        data = {"film_project_id": project_id, "error": message}
    notification_id = _emit(user_id, kind, title=head, body=body, data=data)
    _safe_push_payload(user_id, head, body if ok else "Open the film to retry the export.",
                       {"film_project_id": project_id, "type": kind})
    return notification_id


def notify_workspace_invite(
    user_id: str,
    *,
    workspace_id: str,
    workspace_name: str,
    role: str,
    accept_url: str,
    invite_token: str = "",
) -> Optional[str]:
    """An existing account was invited to a workspace (in-app, no email)."""
    data: dict[str, Any] = {
        "workspace_id": workspace_id, "role": role, "accept_url": accept_url,
    }
    if invite_token:
        data["invite_token"] = invite_token
    name = (workspace_name or "a workspace").strip()[:120]
    return _emit(
        user_id,
        KIND_WORKSPACE_INVITE,
        title=f"You were invited to {name}",
        body=f"You have been invited to join {name} as {role}.",
        data=data,
    )


# --------------------------------------------------------------------------- #
# Convenience dispatcher
# --------------------------------------------------------------------------- #
def emit_for_job(user_id: str, job: Any) -> Optional[str]:
    """Emit the right notification for a job that reached a terminal state.

    Reads the job's ``state``/``id``/``error`` defensively (via ``getattr``) so
    it works with either an ORM ``Job`` row or a lightweight duck-typed stand-in.
    Dispatches to :func:`notify_job_complete` on a completed job and
    :func:`notify_job_failed` on a failed one; a still-processing job (or any
    unreadable input) is a no-op returning ``None``. Fully best-effort — any
    error is swallowed so a job-finalize path can call this unconditionally.
    """
    try:
        state = getattr(job, "state", None)
        job_id = getattr(job, "id", None) or getattr(job, "job_id", None) or ""

        if state == _STATE_COMPLETE:
            return notify_job_complete(user_id, job_id)
        if state == _STATE_FAILED:
            return notify_job_failed(user_id, job_id, getattr(job, "error", ""))
        return None
    except Exception as exc:  # pragma: no cover - defensive belt-and-braces
        logger.warning(f"emit_for_job failed (user={user_id}): {exc}")
        return None


__all__ = [
    "DEFAULT_LOW_CREDITS_THRESHOLD",
    "KIND_JOB_COMPLETE",
    "KIND_JOB_FAILED",
    "KIND_LOW_CREDITS",
    "KIND_REFERRAL_EARNED",
    "KIND_RENDER_COMPLETE",
    "KIND_RENDER_FAILED",
    "KIND_FILM_EXPORT_COMPLETE",
    "KIND_FILM_EXPORT_FAILED",
    "KIND_WORKSPACE_INVITE",
    "emit_for_job",
    "notify_film_export",
    "notify_render_complete",
    "notify_render_failed",
    "notify_workspace_invite",
    "notify_job_complete",
    "notify_job_failed",
    "notify_low_credits",
    "notify_referral_earned",
]
