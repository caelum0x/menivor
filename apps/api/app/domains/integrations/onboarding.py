"""Ads-agent onboarding checklist: credits granted once per workspace (or per user without one).

Steps: connect ad accounts +50, first question +10, first approved action +10.
Idempotency: a row in ``integration_onboarding_grants`` with
``UNIQUE(owner_scope, step)`` is inserted inside a savepoint before the ledger
grant, in the same transaction. A second attempt (a retry, a race, a reconnect)
hits the constraint and grants nothing. Credits land in the existing ledger: the
workspace shared pool for a workspace, the personal pool otherwise.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import IntegrationOnboardingGrant
from app.domains.integrations.scope import Scope

STEPS: tuple[tuple[str, str, int], ...] = (
    ("connect_ad_accounts", "Connect ad accounts", 50),
    ("first_question", "Ask your first question", 10),
    ("first_approved_action", "Approve your first action", 10),
)
_CREDITS = {key: credits for key, _, credits in STEPS}
REASON_PREFIX = "onboarding:"


def grant_once(session: Any, scope: Scope, step: str) -> int:
    """Grant the step's credits if this scope never got them. Returns the credits granted (0 if already)."""
    if step not in _CREDITS:
        raise IntegrationError(400, "Unknown onboarding step.")
    credits = _CREDITS[step]
    try:
        with session.begin_nested():
            session.add(IntegrationOnboardingGrant(owner_scope=scope.owner_scope, step=step, credits=credits,
                                                   user_id=scope.user_id))
            session.flush()
    except IntegrityError:
        return 0
    from app.models.db.repositories import CreditRepository

    repo = CreditRepository(session)
    reason = f"{REASON_PREFIX}{step}"
    if scope.workspace_id:
        repo.workspace_grant(scope.workspace_id, credits, reason, actor_user_id=scope.user_id)
    else:
        repo.grant(scope.user_id, credits, reason)
    session.flush()
    return credits


def checklist(session: Any, scope: Scope) -> dict:
    done = set(session.execute(select(IntegrationOnboardingGrant.step).where(
        IntegrationOnboardingGrant.owner_scope == scope.owner_scope)).scalars())
    steps = [{"key": key, "label": label, "credits": credits, "done": key in done} for key, label, credits in STEPS]
    return {"steps": steps, "earned": sum(s["credits"] for s in steps if s["done"]),
            "total": sum(c for _, _, c in STEPS)}


__all__ = ["REASON_PREFIX", "STEPS", "checklist", "grant_once"]
