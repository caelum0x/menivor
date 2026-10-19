"""Platform-admin service (Enterprise Access & Governance, Epic 1).

This is the ReelForge *staff* surface: cross-tenant listing of users, workspaces
and jobs, plus short-lived impersonation. It is HARD-GATED on ``User.is_staff``
and is deliberately SEPARATE from the per-workspace RBAC roles — a workspace
``owner`` is not a platform admin, and platform-admin status grants nothing
*inside* a workspace. Every public function calls :func:`_require_staff` before
doing anything, so a non-staff caller is rejected with :class:`PermissionError`
(mapped to HTTP ``403`` upstream) and can never reach the cross-tenant data.

Impersonation mints a short-lived, scoped token *record* (a value object — this
module does not itself issue a JWT) and writes an APPEND-ONLY audit row so every
impersonation is accountable.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.db.models import Job, User, Workspace
from app.models.db.repositories import AdminRepository
from app.services import audit

#: How long a minted impersonation token is valid. Short by design — an
#: impersonation session is time-boxed so a leaked token expires quickly.
IMPERSONATION_TTL_SECONDS: int = 15 * 60


@dataclass(frozen=True)
class ImpersonationToken:
    """A short-lived, scoped impersonation grant minted by a platform admin.

    Immutable value object (``frozen``): the opaque ``token`` authenticates a
    time-boxed session in which ``admin_user_id`` acts as ``target_user_id``.
    ``scope`` names the grant, and ``expires_at`` bounds it. ``jti`` is a
    non-secret unique identifier for this grant, safe to record in the audit
    trail so repeated impersonations of the same target are distinguishable and
    a session can later be correlated/revoked. :meth:`is_active` reports whether
    it is still valid at a given instant.
    """

    token: str
    jti: str
    admin_user_id: str
    target_user_id: str
    scope: str
    issued_at: datetime
    expires_at: datetime

    def is_active(self, now: datetime | None = None) -> bool:
        """Return whether the token is still within its validity window."""
        moment = now or datetime.now(timezone.utc)
        return moment < self.expires_at


def _require_staff(session: Session, admin_user_id: str) -> User:
    """Return the acting user iff they are platform staff, else raise.

    The single hard gate for the platform-admin surface: a blank id, an unknown
    user, or a user whose ``is_staff`` is ``False`` all raise
    :class:`PermissionError`. Returned so callers can reuse the row without a
    second lookup.
    """
    normalized = (admin_user_id or "").strip()
    if not normalized:
        raise PermissionError("403: platform-admin access requires a user id")
    user = session.get(User, normalized)
    if user is None or not bool(getattr(user, "is_staff", False)):
        raise PermissionError(
            f"403: user {admin_user_id} is not a platform admin"
        )
    return user


def list_users(
    session: Session, admin_user_id: str, limit: int = 50, offset: int = 0
) -> list[User]:
    """List all users across every tenant (staff-only), newest first, paginated."""
    _require_staff(session, admin_user_id)
    return AdminRepository(session).list_users(limit=limit, offset=offset)


def list_workspaces(
    session: Session, admin_user_id: str, limit: int = 50, offset: int = 0
) -> list[Workspace]:
    """List all workspaces across every tenant (staff-only), newest first."""
    _require_staff(session, admin_user_id)
    return AdminRepository(session).list_workspaces(limit=limit, offset=offset)


def list_jobs(
    session: Session, admin_user_id: str, limit: int = 50, offset: int = 0
) -> list[Job]:
    """List all jobs across every tenant (staff-only), newest first, paginated."""
    _require_staff(session, admin_user_id)
    return AdminRepository(session).list_jobs(limit=limit, offset=offset)


def mint_impersonation(
    session: Session,
    admin_user_id: str,
    target_user_id: str,
    client_ip: str | None = None,
) -> ImpersonationToken:
    """Mint a short-lived scoped impersonation token and audit the action.

    Guards, in order:

    * **Staff-only.** The caller must be platform staff (:func:`_require_staff`),
      else :class:`PermissionError`.
    * **Target must exist.** ``target_user_id`` must resolve to a real user, else
      :class:`ValueError` — a token is never minted for a phantom target.

    On success a time-boxed :class:`ImpersonationToken` (valid for
    :data:`IMPERSONATION_TTL_SECONDS`) is returned AND an append-only audit row
    (``action='admin.impersonated'``) is written recording who impersonated whom
    and when the grant expires — so every impersonation is accountable. The token
    string is a 256-bit URL-safe secret and is NOT persisted here (the audit row
    records the event, never the secret).
    """
    _require_staff(session, admin_user_id)

    normalized_target = (target_user_id or "").strip()
    if not normalized_target or session.get(User, normalized_target) is None:
        raise ValueError("target_user_id must reference an existing user")

    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=IMPERSONATION_TTL_SECONDS)
    scope = f"impersonate:{normalized_target}"
    # Non-secret unique id for this grant; safe to persist in the audit row so
    # repeated impersonations of the same target are distinguishable and the
    # session can later be correlated/revoked. The secret ``token`` is NEVER
    # written to the audit trail.
    jti = secrets.token_hex(16)
    token = ImpersonationToken(
        token=secrets.token_urlsafe(32),
        jti=jti,
        admin_user_id=admin_user_id,
        target_user_id=normalized_target,
        scope=scope,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    audit.record(
        session,
        actor_user_id=admin_user_id,
        action="admin.impersonated",
        target_type="user",
        target_id=normalized_target,
        metadata={
            "jti": jti,
            "scope": scope,
            "expires_at": expires_at.isoformat(),
            "ttl_seconds": IMPERSONATION_TTL_SECONDS,
        },
        ip=client_ip,
    )
    return token


__all__ = [
    "IMPERSONATION_TTL_SECONDS",
    "ImpersonationToken",
    "list_jobs",
    "list_users",
    "list_workspaces",
    "mint_impersonation",
]
