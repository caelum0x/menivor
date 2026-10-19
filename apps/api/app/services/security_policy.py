"""Workspace security-policy service (Identity & SSO, Epic 2).

A workspace owner/admin configures an enterprise login policy — force SSO, bound
session lifetime, restrict email domains, require MFA, restrict source IPs — and
the login path enforces it. Two concerns:

    get_policy() / set_policy()
        Read and (RBAC-gated) write the per-workspace :class:`SecurityPolicy`
        singleton. :func:`set_policy` requires the caller hold
        ``workspace.settings`` in that workspace (:mod:`app.services.rbac`) BEFORE
        any write — a non-member or under-privileged member is rejected — and
        records an audit row (Epic 1) on every change.
    enforce_login_policy()
        Evaluate a login attempt against the workspace's policy and raise
        :class:`PolicyViolation` on the first failing rule (require-SSO, email
        domain, MFA, IP allowlist). Returns silently when the login is permitted.

RBAC is enforced HERE (not just at the API) for the write path, mirroring
:mod:`app.services.audit` (which gates its read on ``audit.read``): the policy is
security-critical, so its mutation is guarded at the service boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.db.repositories import SecurityPolicyRepository
from app.services import audit, rbac

#: Recognized policy fields a :func:`set_policy` call may update.
_POLICY_FIELDS: tuple[str, ...] = (
    "require_sso",
    "session_timeout_min",
    "allowed_email_domains",
    "mfa_required",
    "ip_allowlist",
)


class PolicyViolation(Exception):
    """Raised when a login attempt violates the workspace security policy.

    ``code`` is a stable machine-readable reason (``require_sso`` |
    ``email_domain`` | ``mfa_required`` | ``ip_not_allowed``) the API can map to a
    clear 4xx; the message is human-readable.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LoginContext:
    """The context of a login attempt evaluated by :func:`enforce_login_policy`.

    Immutable. ``method`` is the auth path used (``"sso"`` | ``"password"`` |
    ``"clerk"`` | …); ``mfa`` whether MFA was satisfied; ``ip`` the caller's source
    address; ``email`` the login email (falls back to the user's email).
    """

    method: str = ""
    mfa: bool = False
    ip: str = ""
    email: str = ""


def get_policy(session: Any, workspace_id: str) -> Any | None:
    """Return the workspace's :class:`SecurityPolicy`, or ``None`` when unset."""
    return SecurityPolicyRepository(session).get(workspace_id)


def set_policy(
    session: Any,
    workspace_id: str,
    actor_user_id: str,
    *,
    actor_ip: str | None = None,
    **fields: Any,
) -> Any:
    """Create/update the workspace policy — ``workspace.settings`` gated; audited.

    Authorization runs FIRST: :func:`rbac.require_permission` verifies the actor is
    a member of ``workspace_id`` (tenant isolation) AND that their role grants
    ``workspace.settings`` — a non-member or under-privileged member raises
    :class:`PermissionError` (mapped to 403 upstream) before any write. Only the
    recognized policy fields are applied (validated/normalized in the repository).
    Records an audit row and returns the persisted policy.
    """
    rbac.require_permission(
        session, actor_user_id, workspace_id, rbac.PERM_WORKSPACE_SETTINGS
    )
    applied = {k: v for k, v in fields.items() if k in _POLICY_FIELDS and v is not None}
    policy = SecurityPolicyRepository(session).upsert(workspace_id, **applied)
    audit.record(
        session,
        actor_user_id=actor_user_id,
        action="security_policy.updated",
        workspace_id=workspace_id,
        target_type="security_policy",
        target_id=workspace_id,
        metadata={"fields": sorted(applied.keys())},
        ip=actor_ip,
    )
    return policy


def enforce_login_policy(
    session: Any,
    user: Any,
    workspace_id: str,
    ctx: LoginContext,
) -> None:
    """Enforce the workspace login policy for one attempt; raise on the first breach.

    Rules, in order (each a hard gate; an unset/empty rule is a pass):

    * **require_sso** — when set, the login ``method`` MUST be ``"sso"`` (a
      password / Clerk login is rejected).
    * **allowed_email_domains** — when non-empty, the login email's domain MUST be
      listed.
    * **mfa_required** — when set, ``ctx.mfa`` MUST be true.
    * **ip_allowlist** — when non-empty, ``ctx.ip`` MUST be listed.

    Returns silently when the attempt is permitted (or no policy exists). Raises
    :class:`PolicyViolation` (carrying a stable ``code``) on the first failing rule.
    """
    policy = get_policy(session, workspace_id)
    if policy is None:
        return  # no policy configured -> nothing to enforce

    if getattr(policy, "require_sso", False) and (ctx.method or "").lower() != "sso":
        raise PolicyViolation(
            "require_sso", "this workspace requires signing in via SSO"
        )

    email = (ctx.email or getattr(user, "email", "") or "").strip().lower()
    allowed_domains = [
        str(d).strip().lower()
        for d in (getattr(policy, "allowed_email_domains", None) or [])
        if str(d).strip()
    ]
    if allowed_domains:
        domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if domain not in allowed_domains:
            raise PolicyViolation(
                "email_domain",
                f"email domain {domain or email!r} is not permitted for this workspace",
            )

    if getattr(policy, "mfa_required", False) and not bool(ctx.mfa):
        raise PolicyViolation(
            "mfa_required", "this workspace requires multi-factor authentication"
        )

    ip_allowlist = [
        str(ip).strip()
        for ip in (getattr(policy, "ip_allowlist", None) or [])
        if str(ip).strip()
    ]
    if ip_allowlist and (ctx.ip or "").strip() not in ip_allowlist:
        raise PolicyViolation(
            "ip_not_allowed",
            f"source IP {ctx.ip or '<none>'} is not permitted for this workspace",
        )


__all__ = [
    "LoginContext",
    "PolicyViolation",
    "enforce_login_policy",
    "get_policy",
    "set_policy",
]
