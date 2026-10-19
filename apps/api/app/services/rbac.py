"""RBAC decision engine for ReelForge Enterprise (Access & Governance, Epic 1).

The authorization decision is split into two crisp, independently-testable
concerns:

1. **Tenant isolation (membership).** Is the caller a member of the workspace at
   all? This is looked up from :class:`WorkspaceMember` — a caller with no
   membership row is *not in the tenant* and is denied outright, no matter what
   role string is passed. This is the #1 invariant: no endpoint ever returns
   another tenant's data.
2. **Role -> permission (Casbin).** Given the caller's role in that workspace,
   does the role grant the requested permission? This decision is delegated to
   **pycasbin** (Apache-2.0) — we do NOT hand-roll the decision logic. A
   module-level :class:`casbin.Enforcer` is built once from an in-code RBAC model
   (``conf`` string) plus an in-code policy (role -> permission grants and the
   role-inheritance graph).

The Casbin model is a classic RBAC-with-resource-roles ``sub, obj, act`` model:
``sub`` = the workspace role, ``obj`` = the permission, ``act`` = the constant
``"access"``. Role inheritance ``g`` gives a linear hierarchy
``owner > admin > editor > viewer`` (each role inherits every permission of the
role below it), while ``billing`` is a standalone role outside that chain. The
effect is deny-by-default: a permission is granted only if some policy line
allows it, so an unknown/legacy role (e.g. the additive-layer ``member``) that
carries no policy is denied every permission — fail-closed.

Public API::

    require_permission(session, user_id, workspace_id, permission)  # raise or pass
    is_member(session, user_id, workspace_id) -> bool
    get_role(session, user_id, workspace_id) -> str | None
    effective_permissions(role) -> frozenset[str]
    enforce(role, permission) -> bool
"""

from __future__ import annotations

from casbin import Enforcer, Model
from sqlalchemy.orm import Session

from app.models.db.repositories import WorkspaceRepository

# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
#: The five workspace roles (Enterprise). The workspace creator is always the
#: single ``owner``. ``owner > admin > editor > viewer`` form a linear
#: inheritance chain; ``billing`` is a standalone finance role outside it.
ROLE_OWNER: str = "owner"
ROLE_ADMIN: str = "admin"
ROLE_EDITOR: str = "editor"
ROLE_VIEWER: str = "viewer"
ROLE_BILLING: str = "billing"

ROLES: frozenset[str] = frozenset(
    {ROLE_OWNER, ROLE_ADMIN, ROLE_EDITOR, ROLE_VIEWER, ROLE_BILLING}
)

# --------------------------------------------------------------------------- #
# Permission catalog
# --------------------------------------------------------------------------- #
#: The permissions a role may hold. Stable dotted strings referenced by every
#: guarded call site so a typo is a NameError, not a silent allow.
PERM_JOBS_CREATE: str = "jobs.create"
PERM_JOBS_READ: str = "jobs.read"
PERM_MEMBERS_MANAGE: str = "members.manage"
PERM_BILLING_MANAGE: str = "billing.manage"
PERM_WORKSPACE_SETTINGS: str = "workspace.settings"
PERM_AUDIT_READ: str = "audit.read"
PERM_ADMIN_ACCESS: str = "admin.access"
PERM_WALLET_TRANSFER: str = "wallet.transfer"

PERMISSIONS: frozenset[str] = frozenset(
    {
        PERM_JOBS_CREATE,
        PERM_JOBS_READ,
        PERM_MEMBERS_MANAGE,
        PERM_BILLING_MANAGE,
        PERM_WORKSPACE_SETTINGS,
        PERM_AUDIT_READ,
        PERM_ADMIN_ACCESS,
        PERM_WALLET_TRANSFER,
    }
)

#: The constant action verb of every request/policy (``sub, obj, act`` model).
ACTION: str = "access"

# --------------------------------------------------------------------------- #
# Casbin RBAC model (in-code ``conf`` string — no files on disk)
# --------------------------------------------------------------------------- #
#: sub = role, obj = permission, act = ACTION. ``g`` is the role-inheritance
#: graph. Deny-by-default effect: allow iff some policy line matches.
_MODEL_CONF: str = """
[request_definition]
r = sub, obj, act

[policy_definition]
p = sub, obj, act

[role_definition]
g = _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub) && r.obj == p.obj && r.act == p.act
"""

#: Role-inheritance edges ``(child, parent)``: the child inherits every
#: permission granted to the parent. A linear chain owner -> admin -> editor ->
#: viewer; ``billing`` is intentionally absent (standalone finance role).
_ROLE_LINKS: tuple[tuple[str, str], ...] = (
    (ROLE_OWNER, ROLE_ADMIN),
    (ROLE_ADMIN, ROLE_EDITOR),
    (ROLE_EDITOR, ROLE_VIEWER),
)

#: Permissions granted DIRECTLY to each role (inherited permissions come from the
#: ``g`` chain above). Effective sets after inheritance:
#:   viewer  -> {jobs.read}
#:   editor  -> {jobs.create, jobs.read}
#:   admin   -> {members.manage, workspace.settings, audit.read, jobs.create, jobs.read}
#:   owner   -> ALL permissions
#:   billing -> {billing.manage, jobs.read}
_DIRECT_GRANTS: dict[str, tuple[str, ...]] = {
    ROLE_VIEWER: (PERM_JOBS_READ,),
    ROLE_EDITOR: (PERM_JOBS_CREATE,),
    ROLE_ADMIN: (
        PERM_MEMBERS_MANAGE,
        PERM_WORKSPACE_SETTINGS,
        PERM_AUDIT_READ,
        PERM_WALLET_TRANSFER,
    ),
    ROLE_OWNER: (PERM_BILLING_MANAGE, PERM_ADMIN_ACCESS),
    ROLE_BILLING: (PERM_BILLING_MANAGE, PERM_JOBS_READ),
}


def _build_enforcer() -> Enforcer:
    """Build the module-level Casbin enforcer from the in-code model + policy.

    No adapter is passed, so the policy lives purely in memory (there is no
    storage-backed policy to load or persist). Grouping edges and grant lines are
    added programmatically from :data:`_ROLE_LINKS` / :data:`_DIRECT_GRANTS`.
    """
    model = Model()
    model.load_model_from_text(_MODEL_CONF)
    enforcer = Enforcer(model)
    for child, parent in _ROLE_LINKS:
        enforcer.add_named_grouping_policy("g", child, parent)
    for role, permissions in _DIRECT_GRANTS.items():
        for permission in permissions:
            enforcer.add_policy(role, permission, ACTION)
    return enforcer


#: The single, process-wide RBAC decision engine. Pure role -> permission logic
#: (it holds no tenant/membership state), so it is safe to share across requests.
_ENFORCER: Enforcer = _build_enforcer()


# --------------------------------------------------------------------------- #
# Decision API
# --------------------------------------------------------------------------- #
def enforce(role: str | None, permission: str) -> bool:
    """Return whether ``role`` grants ``permission`` (pure Casbin decision).

    A ``None`` / blank / unknown role is denied (fail-closed): the enforcer has
    no policy for it, so every permission evaluates to ``False``. This is the
    role -> permission half of the decision only; it performs NO membership /
    tenant check (that is :func:`is_member` / :func:`require_permission`).
    """
    if not role:
        return False
    return bool(_ENFORCER.enforce(role, permission, ACTION))


def effective_permissions(role: str | None) -> frozenset[str]:
    """Return the full set of permissions ``role`` holds (direct + inherited).

    Computed by evaluating every permission in the catalog through the enforcer,
    so the result always reflects the live policy + inheritance graph. An unknown
    / blank role yields the empty set.
    """
    if not role:
        return frozenset()
    return frozenset(p for p in PERMISSIONS if enforce(role, p))


def get_role(
    session: Session, user_id: str, workspace_id: str
) -> str | None:
    """Return the caller's role in the workspace, or ``None`` if not a member.

    A ``None`` result is the tenant-isolation signal: the caller has no
    membership row, so they are not in this tenant and may see nothing.
    """
    membership = WorkspaceRepository(session).get_membership(
        workspace_id, user_id
    )
    return membership.role if membership is not None else None


def is_member(session: Session, user_id: str, workspace_id: str) -> bool:
    """Return whether ``user_id`` is a member of ``workspace_id`` (tenant gate)."""
    return (
        WorkspaceRepository(session).get_membership(workspace_id, user_id)
        is not None
    )


def require_permission(
    session: Session,
    user_id: str,
    workspace_id: str,
    permission: str,
) -> str:
    """Authorize ``user_id`` for ``permission`` in ``workspace_id`` or raise.

    Two gates, in order:

    1. **Tenant isolation.** Look up the caller's :class:`WorkspaceMember`. No
       membership row -> :class:`PermissionError` (the caller is not in this
       tenant). This is the load-bearing isolation check — it runs before any
       role logic so a non-member is rejected identically regardless of the
       permission requested.
    2. **Role -> permission.** Feed the caller's role to the Casbin enforcer;
       if it does not grant ``permission`` -> :class:`PermissionError`.

    On success the caller's role string is returned so a controller can reuse it
    without a second lookup. Raises :class:`PermissionError` (which the API layer
    maps to HTTP ``403``) on either failure.
    """
    role = get_role(session, user_id, workspace_id)
    if role is None:
        raise PermissionError(
            f"403: user {user_id} is not a member of workspace {workspace_id}"
        )
    if not enforce(role, permission):
        raise PermissionError(
            f"403: role '{role}' lacks permission '{permission}'"
        )
    return role


__all__ = [
    "ACTION",
    "PERMISSIONS",
    "PERM_ADMIN_ACCESS",
    "PERM_AUDIT_READ",
    "PERM_BILLING_MANAGE",
    "PERM_JOBS_CREATE",
    "PERM_JOBS_READ",
    "PERM_MEMBERS_MANAGE",
    "PERM_WORKSPACE_SETTINGS",
    "PERM_WALLET_TRANSFER",
    "ROLES",
    "ROLE_ADMIN",
    "ROLE_BILLING",
    "ROLE_EDITOR",
    "ROLE_OWNER",
    "ROLE_VIEWER",
    "effective_permissions",
    "enforce",
    "get_role",
    "is_member",
    "require_permission",
]
