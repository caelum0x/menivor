"""Consent capture + lookup (GDPR / SOC2 — Compliance, Epic 5).

Thin, append-only service over :class:`ConsentRepository`:

* :func:`record_consent` appends an immutable consent decision and audits it.
* :func:`get_consent` returns the CURRENT (newest) decision for a
  ``(user_id, kind)`` pair.
* :func:`list_consents` returns a user's full consent trail.

Every read/write is strictly scoped to the requesting ``user_id`` — a caller can
never read or record another user's consent.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.db.repositories import ConsentRepository
from app.services import audit

#: Audit verb recorded on a consent decision.
_ACTION_CONSENT: str = "compliance.consent_recorded"


def record_consent(
    session: Session,
    user_id: str,
    kind: str,
    granted: bool,
    version: str = "",
) -> Any:
    """Append an immutable consent decision for ``user_id`` and audit it.

    ``kind`` is a consent dimension (e.g. ``tos`` | ``marketing`` |
    ``ai_disclosure``); ``granted`` records grant/withdrawal; ``version`` is the
    policy version the decision was made against. Returns the new
    :class:`ConsentRecord`.

    Raises:
        ValueError: when ``user_id`` or ``kind`` is blank.
    """
    normalized_user = (user_id or "").strip()
    if not normalized_user:
        raise ValueError("user_id must be a non-empty string")
    normalized_kind = (kind or "").strip()
    if not normalized_kind:
        raise ValueError("kind must be a non-empty string")

    record = ConsentRepository(session).create(
        normalized_user, normalized_kind, bool(granted), version=version
    )
    audit.record(
        session,
        actor_user_id=normalized_user,
        action=_ACTION_CONSENT,
        target_type="consent",
        target_id=record.id,
        metadata={
            "kind": record.kind,
            "granted": record.granted,
            "version": record.version,
        },
    )
    if record.kind.strip().lower() == "marketing":
        _rally_consent(normalized_user, bool(record.granted), record.id)
    return record


def _rally_consent(user_id: str, granted: bool, record_id: Any) -> None:
    """Mirror a lifecycle-email consent decision to Rally (no-op unless configured)."""
    try:
        from app.integrations.rally import track_email_consent

        track_email_consent(user_id, granted, record_id)
    except Exception as exc:  # noqa: BLE001 - consent capture must never fail on Rally
        from loguru import logger

        logger.debug(f"rally consent event skipped: {exc}")


def get_consent(session: Session, user_id: str, kind: str) -> Any:
    """Return the CURRENT (newest) consent decision for ``(user_id, kind)``.

    Owner-scoped: only ``user_id``'s own rows are considered. Returns ``None``
    when the user has never made a decision for ``kind``.
    """
    return ConsentRepository(session).get_latest(user_id, kind)


def list_consents(session: Session, user_id: str) -> list[Any]:
    """Return a user's full consent trail, oldest first (owner-scoped)."""
    return ConsentRepository(session).list_for_user(user_id)


__all__ = ["get_consent", "list_consents", "record_consent"]
