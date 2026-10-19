"""Expo push delivery — the out-of-app counterpart to the in-app notification.

Where :mod:`app.services.notifications` writes an in-app
:class:`~app.models.db.models.Notification` row (the bell + unread badge) and
:mod:`app.services.webhooks` POSTs a job's completion to a user-registered
callback URL, this module delivers a **native push** to the user's registered
devices via Expo's push service
(https://exp.host/--/api/v2/push/send) so a finished render reaches them even
when the app is backgrounded.

Design rules
------------
* **Best-effort (CRITICAL).** Sending a push must NEVER fail the caller. Every
  public function opens its own short-lived DB session, swallows *all* errors
  (logging them), and returns a small non-sensitive summary dict. A push
  failure must never abort a render, a credit grant, or a referral redemption.
* **Token hygiene.** An Expo push token is SENSITIVE (it maps to a device's
  APNs/FCM identity) and is NEVER logged — only counts and non-sensitive
  receipt statuses are. Nothing here writes a token into a log line.
* **Env-gated auth.** ``EXPO_ACCESS_TOKEN`` is OPTIONAL: Expo push works without
  it for most projects. When set it is sent as a ``Bearer`` header; when unset
  the header is simply omitted (no secret is required for the module to work).
* **Self-healing.** A token Expo reports as ``DeviceNotRegistered`` is flipped
  ``is_active=False`` (via :class:`PushTokenRepository`) so it never retries.
* **Import-safe.** ``requests`` and the persistence layer are imported behind
  guards so merely importing this module never crashes a stripped-down worker
  image or a ``py_compile`` sanity check; when a dependency is absent the send
  degrades to a logged no-op that returns a summary rather than raising.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from loguru import logger

# ``requests`` is a first-party dependency, but guard the import so this module
# still ``py_compile``s / imports in stripped-down environments (mirrors
# ``app/services/webhooks.py``).
try:  # pragma: no cover - exercised indirectly via monkeypatching
    import requests  # type: ignore
except Exception:  # pragma: no cover - requests is normally installed
    requests = None  # type: ignore

# Guarded persistence-layer imports. When absent the send degrades to a logged
# no-op (consistent with the best-effort contract).
try:  # pragma: no cover - exercised indirectly; failure path is defensive
    from app.models.db import get_session
    from app.models.db.repositories import PushTokenRepository
except Exception as _exc:  # pragma: no cover - only when the DB layer is absent
    get_session = None  # type: ignore[assignment]
    PushTokenRepository = None  # type: ignore[assignment]
    logger.warning(f"push persistence layer unavailable: {_exc}")

try:
    from app.config import config  # type: ignore
except Exception:  # pragma: no cover - keep import-safe without full app config
    config = None  # type: ignore


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
#: Expo's push send endpoint. Overridable via ``config.app`` for tests / staging.
EXPO_PUSH_URL: str = "https://exp.host/--/api/v2/push/send"

#: Expo accepts up to 100 messages per request; chunk larger fan-outs.
_MAX_BATCH: int = 100

#: Per-request timeout (seconds) for the Expo call.
DEFAULT_TIMEOUT_S: float = 10.0

#: Valid Expo token prefixes. A value not matching one of these is skipped
#: before any network call (never sent, never logged).
_EXPO_TOKEN_PREFIXES: tuple[str, ...] = ("ExponentPushToken[", "ExpoPushToken[")

#: The Expo receipt error that means the token is permanently dead — flip it
#: inactive so it drops out of every future send.
_ERROR_DEVICE_NOT_REGISTERED: str = "DeviceNotRegistered"

_USER_AGENT: str = "ReelForge-Push/1.0"

# Push copy for render lifecycle events (mirrors the in-app notification titles).
_TITLE_JOB_COMPLETE: str = "Your video is ready"
_BODY_JOB_COMPLETE: str = "Your reel has finished rendering and is ready to view."
_TITLE_JOB_FAILED: str = "Your video failed to render"
_BODY_JOB_FAILED: str = "Something went wrong while rendering your reel."


# --------------------------------------------------------------------------- #
# Config / auth helpers
# --------------------------------------------------------------------------- #
def _expo_access_token() -> str:
    """Return the optional Expo access token (env first, then app config).

    ``EXPO_ACCESS_TOKEN`` is OPTIONAL — Expo push works without it for most
    projects. Returns ``""`` when unset, in which case no ``Authorization``
    header is sent. Read defensively so a missing config section never raises.
    """
    token = os.getenv("EXPO_ACCESS_TOKEN", "") or ""
    if token:
        return token
    if config is not None:
        try:
            return str(config.app.get("expo_access_token", "") or "")
        except Exception:  # pragma: no cover - defensive; config shape drift
            return ""
    return ""


def _push_url() -> str:
    """Resolve the Expo push URL (config-overridable, defaults to Expo)."""
    if config is not None:
        try:
            override = str(config.app.get("expo_push_url", "") or "")
            if override:
                return override
        except Exception:  # pragma: no cover - defensive
            pass
    return EXPO_PUSH_URL


def _timeout_s() -> float:
    """Resolve the per-request timeout (config-overridable)."""
    if config is not None:
        try:
            raw = config.app.get("expo_push_timeout_s", DEFAULT_TIMEOUT_S)
            value = float(raw)
            if value > 0:
                return value
        except Exception:  # pragma: no cover - defensive
            pass
    return DEFAULT_TIMEOUT_S


def _is_valid_expo_token(token: str) -> bool:
    """Return whether ``token`` is a well-formed Expo push token.

    A malformed value is skipped before any network call so we never post — or
    log — garbage, and never waste an Expo request on an unroutable token.
    """
    return isinstance(token, str) and token.startswith(_EXPO_TOKEN_PREFIXES)


def _chunk(items: list[Any], size: int) -> list[list[Any]]:
    """Split ``items`` into contiguous chunks of at most ``size``."""
    return [items[i : i + size] for i in range(0, len(items), size)]


# --------------------------------------------------------------------------- #
# Expo transport (best-effort)
# --------------------------------------------------------------------------- #
def _post_batch(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """POST one batch of messages to Expo and return the aligned tickets.

    Returns the ``data`` list from Expo's response — one ticket per message, in
    order — or an empty list on any transport/parse failure (best-effort: the
    caller treats an empty result as "nothing to invalidate"). Never raises.
    """
    if requests is None or not messages:
        return []

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    }
    access_token = _expo_access_token()
    if access_token:
        # Sent only over TLS to Expo; never logged.
        headers["Authorization"] = f"Bearer {access_token}"

    try:
        response = requests.post(
            _push_url(),
            json=messages,
            headers=headers,
            timeout=_timeout_s(),
        )
        response.raise_for_status()
        body = response.json()
    except Exception as exc:  # noqa: BLE001 - transport/parse errors are swallowed
        logger.warning(f"expo push batch failed ({len(messages)} msg): {exc}")
        return []

    tickets = body.get("data") if isinstance(body, dict) else None
    return tickets if isinstance(tickets, list) else []


def _handle_tickets(
    repo: Any,
    tokens: list[str],
    tickets: list[dict[str, Any]],
) -> int:
    """Process Expo tickets aligned to ``tokens``; deactivate dead tokens.

    Expo returns one ticket per message in request order, so ``tickets[i]``
    corresponds to ``tokens[i]``. A ticket with ``status == "error"`` and
    ``details.error == "DeviceNotRegistered"`` means that token is permanently
    dead — flip it inactive (self-healing). Returns the number deactivated.
    Tokens are never logged; only the count + coarse status are.
    """
    deactivated = 0
    for token, ticket in zip(tokens, tickets):
        if not isinstance(ticket, dict):
            continue
        if ticket.get("status") != "error":
            continue
        details = ticket.get("details")
        error = details.get("error") if isinstance(details, dict) else None
        if error == _ERROR_DEVICE_NOT_REGISTERED:
            try:
                deactivated += repo.deactivate_by_token(token)
            except Exception as exc:  # noqa: BLE001 - invalidation is best-effort
                logger.warning(f"push token invalidation failed: {exc}")
    return deactivated


# --------------------------------------------------------------------------- #
# Public send API (all best-effort)
# --------------------------------------------------------------------------- #
def send_to_user(
    user_id: str,
    title: str,
    body: str,
    data: Optional[dict[str, Any]] = None,
) -> dict[str, int]:
    """Deliver a push to every active device of ``user_id`` (best-effort).

    Looks up the owner's active Expo tokens, batches them to Expo's push API,
    and self-heals any ``DeviceNotRegistered`` token. Returns a small,
    non-sensitive summary (``{"devices", "sent", "deactivated"}``); never raises
    and never logs a token. Degrades to a logged no-op (all-zero summary) when
    ``user_id`` is empty or the persistence / HTTP layer is unavailable.
    """
    summary = {"devices": 0, "sent": 0, "deactivated": 0}
    if not user_id:
        return summary
    if get_session is None or PushTokenRepository is None:
        logger.warning("push send skipped: persistence unavailable")
        return summary
    if requests is None:
        logger.warning("push send skipped: HTTP client unavailable")
        return summary

    payload = dict(data or {})
    try:
        with get_session() as session:
            repo = PushTokenRepository(session)
            rows = repo.list_active_for_user(user_id)
            tokens = [
                r.token for r in rows if _is_valid_expo_token(getattr(r, "token", ""))
            ]
            summary["devices"] = len(tokens)
            if not tokens:
                return summary

            sent = 0
            deactivated = 0
            for chunk in _chunk(tokens, _MAX_BATCH):
                messages = [
                    {"to": token, "title": title, "body": body, "data": payload}
                    for token in chunk
                ]
                tickets = _post_batch(messages)
                if tickets:
                    sent += sum(
                        1
                        for t in tickets
                        if isinstance(t, dict) and t.get("status") == "ok"
                    )
                    deactivated += _handle_tickets(repo, chunk, tickets)

            summary["sent"] = sent
            summary["deactivated"] = deactivated
    except Exception as exc:  # noqa: BLE001 - a push must never crash the caller
        logger.warning(f"push send failed (user={user_id}): {exc}")
        return summary

    logger.info(
        f"push sent (user={user_id}): devices={summary['devices']} "
        f"sent={summary['sent']} deactivated={summary['deactivated']}"
    )
    return summary


def send_job_complete(user_id: str, job_id: str) -> dict[str, int]:
    """Push a 'video ready' notification for a finished render (best-effort)."""
    return send_to_user(
        user_id,
        title=_TITLE_JOB_COMPLETE,
        body=_BODY_JOB_COMPLETE,
        data={"job_id": job_id, "type": "job_complete"},
    )


def send_job_failed(user_id: str, job_id: str) -> dict[str, int]:
    """Push a 'render failed' notification for a failed job (best-effort)."""
    return send_to_user(
        user_id,
        title=_TITLE_JOB_FAILED,
        body=_BODY_JOB_FAILED,
        data={"job_id": job_id, "type": "job_failed"},
    )


__all__ = [
    "EXPO_PUSH_URL",
    "send_to_user",
    "send_job_complete",
    "send_job_failed",
]
