"""Pure team spend-role policy (no DB): which workspace role may do what.

Governs three shared-pool capabilities (PRODUCT_ROADMAP.md C — team roles on
spend):

* ``topup``          — add credit to the workspace wallet (owner/admin)
* ``manage_policy``  — set the workspace budget / BYOK consent / spend role (owner/admin)
* ``spend``          — draw the shared pool to fund a job (>= the workspace's
  configurable ``min_spend_role``, default ``member``)

Kept side-effect free so the matrix is unit-testable; the service resolves the
caller's role and enforces it.
"""

from __future__ import annotations

# Higher rank = more privilege. Unknown roles rank 0 (no privilege).
_RANK = {"owner": 3, "admin": 2, "member": 1}

TOPUP = "topup"
MANAGE_POLICY = "manage_policy"
SPEND = "spend"

# Actions that always require an admin-or-owner.
_ADMIN_ACTIONS = {TOPUP, MANAGE_POLICY}

VALID_MIN_SPEND_ROLES = ("owner", "admin", "member")


def rank(role: str | None) -> int:
    return _RANK.get(str(role or "").strip().lower(), 0)


def can(action: str, role: str | None, *, min_spend_role: str = "member") -> bool:
    """Whether ``role`` may perform ``action`` on the workspace shared pool.

    ``topup`` / ``manage_policy`` require admin+. ``spend`` requires at least the
    workspace's ``min_spend_role`` (an operator can restrict spending to admins).
    """
    caller = rank(role)
    if caller <= 0:
        return False
    if action in _ADMIN_ACTIONS:
        return caller >= _RANK["admin"]
    if action == SPEND:
        floor = rank(min_spend_role) or _RANK["member"]
        return caller >= floor
    return False


def normalize_min_spend_role(value: str | None) -> str:
    """Coerce a requested min-spend role to a valid one (default 'member')."""
    role = str(value or "").strip().lower()
    return role if role in VALID_MIN_SPEND_ROLES else "member"
