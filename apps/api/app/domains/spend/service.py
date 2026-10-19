"""Spend-policy service: budget cap + BYOK consent, per user OR workspace.

Period spend is the sum of ``usage_records.cost_micros`` for the owner's wallet
account in the current calendar month. :meth:`ensure_within_budget` is called at
reservation time so a job cannot be dispatched once the month's spend would
exceed the cap. Every method accepts exactly one owner: ``user_id`` (personal)
or ``workspace_id`` (shared pool) — the personal-first signatures are preserved
and workspace variants layer on top.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.spend import roles
from app.domains.wallet.repository import WalletRepository
from app.models.db.marketplace import SpendPolicy, UsageRecord


class SpendError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _month_start_naive_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


class SpendPolicyService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._wallet = WalletRepository(session)

    # ------------------------------------------------------------------ #
    # Owner resolution (exactly one of user_id / workspace_id)
    # ------------------------------------------------------------------ #
    def _get_policy(
        self, *, user_id: str | None = None, workspace_id: str | None = None
    ) -> SpendPolicy | None:
        if workspace_id:
            stmt = select(SpendPolicy).where(SpendPolicy.workspace_id == workspace_id)
        else:
            stmt = select(SpendPolicy).where(SpendPolicy.user_id == user_id)
        return self._session.execute(stmt).scalars().first()

    def _account_id(
        self, *, user_id: str | None, workspace_id: str | None
    ) -> str | None:
        if workspace_id:
            account = self._wallet.get_workspace_account(workspace_id)
        else:
            account = self._wallet.get_personal_account(user_id)
        return account.id if account is not None else None

    def _period_spend(self, account_id: str | None) -> int:
        if not account_id:
            return 0
        stmt = select(func.coalesce(func.sum(UsageRecord.cost_micros), 0)).where(
            UsageRecord.account_id == account_id,
            UsageRecord.created_at >= _month_start_naive_utc(),
        )
        return int(self._session.execute(stmt).scalar_one() or 0)

    # ------------------------------------------------------------------ #
    # Personal API (unchanged signatures)
    # ------------------------------------------------------------------ #
    def get_policy(self, user_id: str) -> SpendPolicy | None:
        return self._get_policy(user_id=user_id)

    def period_spend_micros(self, user_id: str) -> int:
        return self._period_spend(self._account_id(user_id=user_id, workspace_id=None))

    def byok_allowed(self, user_id: str) -> bool:
        return bool(getattr(self._get_policy(user_id=user_id), "byok_allowed", False))

    def policy_view(self, user_id: str) -> dict:
        return self._view(user_id=user_id)

    def upsert_policy(
        self,
        user_id: str,
        *,
        monthly_budget_micros: int | None = None,
        byok_allowed: bool | None = None,
    ) -> dict:
        return self._upsert(
            user_id=user_id,
            monthly_budget_micros=monthly_budget_micros,
            byok_allowed=byok_allowed,
        )

    def ensure_within_budget(self, user_id: str, amount_micros: int) -> None:
        self._ensure(user_id=user_id, workspace_id=None, amount_micros=amount_micros)

    # ------------------------------------------------------------------ #
    # Workspace API
    # ------------------------------------------------------------------ #
    def workspace_policy_view(self, workspace_id: str) -> dict:
        return self._view(workspace_id=workspace_id)

    def upsert_workspace_policy(
        self,
        workspace_id: str,
        *,
        monthly_budget_micros: int | None = None,
        byok_allowed: bool | None = None,
        spend_min_role: str | None = None,
    ) -> dict:
        return self._upsert(
            workspace_id=workspace_id,
            monthly_budget_micros=monthly_budget_micros,
            byok_allowed=byok_allowed,
            spend_min_role=spend_min_role,
        )

    def ensure_within_budget_workspace(
        self, workspace_id: str, amount_micros: int
    ) -> None:
        self._ensure(
            user_id=None, workspace_id=workspace_id, amount_micros=amount_micros
        )

    # ------------------------------------------------------------------ #
    # Shared implementations
    # ------------------------------------------------------------------ #
    def _view(
        self, *, user_id: str | None = None, workspace_id: str | None = None
    ) -> dict:
        policy = self._get_policy(user_id=user_id, workspace_id=workspace_id)
        return {
            "scope": "workspace" if workspace_id else "user",
            "monthly_budget_micros": int(
                getattr(policy, "monthly_budget_micros", 0) or 0
            ),
            "byok_allowed": bool(getattr(policy, "byok_allowed", False)),
            "spend_min_role": str(getattr(policy, "spend_min_role", "member") or "member"),
            "period_spend_micros": self._period_spend(
                self._account_id(user_id=user_id, workspace_id=workspace_id)
            ),
        }

    def _upsert(
        self,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
        monthly_budget_micros: int | None = None,
        byok_allowed: bool | None = None,
        spend_min_role: str | None = None,
    ) -> dict:
        policy = self._get_policy(user_id=user_id, workspace_id=workspace_id)
        if policy is None:
            policy = SpendPolicy(user_id=user_id, workspace_id=workspace_id)
            self._session.add(policy)
        if monthly_budget_micros is not None:
            policy.monthly_budget_micros = max(0, int(monthly_budget_micros))
        if byok_allowed is not None:
            policy.byok_allowed = bool(byok_allowed)
        if spend_min_role is not None:
            policy.spend_min_role = roles.normalize_min_spend_role(spend_min_role)
        policy.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return self._view(user_id=user_id, workspace_id=workspace_id)

    # ------------------------------------------------------------------ #
    # Team spend roles (workspace shared pool)
    # ------------------------------------------------------------------ #
    def workspace_role(self, workspace_id: str, user_id: str) -> str | None:
        """The caller's role in ``workspace_id`` (owner|admin|member), or None."""
        try:
            from app.services import workspaces as ws_service
        except Exception:  # noqa: BLE001 - workspaces layer optional
            return None
        membership = ws_service.get_membership(self._session, workspace_id, user_id)
        return getattr(membership, "role", None) if membership is not None else None

    def assert_can(self, action: str, workspace_id: str, user_id: str) -> None:
        """Raise :class:`SpendError` (403) if the caller may not do ``action``.

        ``action`` is one of :mod:`roles` (topup|manage_policy|spend). Personal
        (non-workspace) contexts are always permitted — the owner is the user.
        """
        if not workspace_id:
            return
        role = self.workspace_role(workspace_id, user_id)
        policy = self._get_policy(workspace_id=workspace_id)
        min_spend_role = str(getattr(policy, "spend_min_role", "member") or "member")
        if not roles.can(action, role, min_spend_role=min_spend_role):
            raise SpendError(
                403,
                f"your workspace role ('{role or 'none'}') cannot {action} the shared pool",
            )

    def _ensure(
        self,
        *,
        user_id: str | None,
        workspace_id: str | None,
        amount_micros: int,
    ) -> None:
        """Raise :class:`SpendError` (402) if reserving breaches the budget."""
        policy = self._get_policy(user_id=user_id, workspace_id=workspace_id)
        budget = int(getattr(policy, "monthly_budget_micros", 0) or 0)
        if budget <= 0:
            return
        spent = self._period_spend(
            self._account_id(user_id=user_id, workspace_id=workspace_id)
        )
        projected = spent + max(0, int(amount_micros))
        if projected > budget:
            scope = "workspace" if workspace_id else "monthly"
            raise SpendError(
                402,
                f"{scope} spend budget exceeded (budget={budget} micros, "
                f"would reach {projected})",
            )
