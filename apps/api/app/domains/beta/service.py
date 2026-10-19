"""Private-beta waitlist rules: normalise, dedupe, approve, check.

Pure-ish service over a SQLAlchemy session. Emails are normalised (trimmed,
lower-cased) and validated with a conservative shape check so the unique index
is the single dedupe authority. Re-requesting with the same email never creates
a second row — it bumps ``request_count`` and keeps the original status, so a
pending requester cannot reset or probe an approval.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.domains.beta.models import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REVOKED,
    STATUSES,
    BetaAccessRequest,
)

MAX_EMAIL_LEN = 254
MAX_USE_CASE_LEN = 2000
MAX_SOURCE_LEN = 40
MAX_LIST_LIMIT = 500

# Deliberately conservative: one @, a dotted domain, no whitespace/control chars.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


class BetaError(ValueError):
    """An invalid beta-waitlist operation."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalize_email(raw: Any) -> str:
    """Trimmed, lower-cased email or ``BetaError`` when it is not email-shaped."""
    email = str(raw or "").strip().lower()
    if not email or len(email) > MAX_EMAIL_LEN or not _EMAIL_RE.match(email):
        raise BetaError("a valid email address is required")
    return email


def _clean_text(raw: Any, limit: int) -> str:
    text = "".join(ch for ch in str(raw or "") if ch == "\n" or ch >= " ")
    return text.strip()[:limit]


def request_access(session: Any, *, email: str, use_case: str = "", source: str = "") -> tuple[BetaAccessRequest, bool]:
    """Record (or dedupe) a waitlist request. Returns ``(row, created)``."""
    normalized = normalize_email(email)
    row = session.query(BetaAccessRequest).filter(BetaAccessRequest.email == normalized).one_or_none()
    cleaned_use_case = _clean_text(use_case, MAX_USE_CASE_LEN)
    if row is not None:
        row.request_count = int(row.request_count or 0) + 1
        if cleaned_use_case and not row.use_case:
            row.use_case = cleaned_use_case
        session.flush()
        return row, False
    row = BetaAccessRequest(
        email=normalized,
        use_case=cleaned_use_case,
        source=_clean_text(source, MAX_SOURCE_LEN),
        status=STATUS_PENDING,
        request_count=1,
    )
    session.add(row)
    session.flush()
    return row, True


def list_requests(session: Any, *, status: str = "", limit: int = 100) -> list[BetaAccessRequest]:
    query = session.query(BetaAccessRequest)
    if status:
        if status not in STATUSES:
            raise BetaError(f"status must be one of {sorted(STATUSES)}")
        query = query.filter(BetaAccessRequest.status == status)
    bounded = max(1, min(int(limit), MAX_LIST_LIMIT))
    return query.order_by(BetaAccessRequest.created_at.desc()).limit(bounded).all()


def set_status(session: Any, *, email: str, approved: bool) -> BetaAccessRequest:
    """Approve (creating the row if the operator invites directly) or revoke."""
    normalized = normalize_email(email)
    row = session.query(BetaAccessRequest).filter(BetaAccessRequest.email == normalized).one_or_none()
    if row is None:
        if not approved:
            raise BetaError("no beta request for that email", status_code=404)
        row = BetaAccessRequest(email=normalized, source="operator_invite", request_count=0)
        session.add(row)
    if approved:
        row.status = STATUS_APPROVED
        row.approved_at = datetime.now(timezone.utc)
    else:
        row.status = STATUS_REVOKED
        row.approved_at = None
    session.flush()
    return row


def is_email_approved(session: Any, email: Any) -> bool:
    """True only for a well-formed email with an ``approved`` waitlist row.

    Fails closed: a malformed email, a missing table/row or any DB error is
    ``False``. Callers must pass an email the identity provider VERIFIED.
    """
    try:
        normalized = normalize_email(email)
    except BetaError:
        return False
    try:
        row = (
            session.query(BetaAccessRequest.status)
            .filter(BetaAccessRequest.email == normalized)
            .one_or_none()
        )
    except Exception:  # noqa: BLE001 - fail closed (e.g. table not migrated yet)
        return False
    return row is not None and row[0] == STATUS_APPROVED


def request_view(row: BetaAccessRequest) -> dict[str, Any]:
    """Operator-facing view (admin endpoints only)."""
    return {
        "id": row.id,
        "email": row.email,
        "use_case": row.use_case,
        "source": row.source,
        "status": row.status,
        "request_count": row.request_count,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


__all__ = [
    "BetaError",
    "STATUS_APPROVED",
    "STATUS_PENDING",
    "STATUS_REVOKED",
    "is_email_approved",
    "list_requests",
    "normalize_email",
    "request_access",
    "request_view",
    "set_status",
]
