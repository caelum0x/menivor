"""Marketplace usage analytics — cost attribution by model/provider/stage/day.

Aggregates ``usage_records`` (the normalized provider cost the wallet settles)
for a caller's personal wallet or a workspace shared pool over a recent window,
so a creator/admin can see exactly where their spend goes. Read-only; owner
scoped through the resolved wallet account.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.money import micros_to_usd_str
from app.domains.wallet.repository import WalletRepository
from app.models.db.marketplace import UsageRecord


def _since(days: int) -> datetime:
    days = max(1, min(365, int(days)))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now - timedelta(days=days)


class UsageAnalyticsService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._wallet = WalletRepository(session)

    def _account_id(self, user_id: str, workspace_id: str | None) -> str | None:
        account = (
            self._wallet.get_workspace_account(workspace_id)
            if workspace_id
            else self._wallet.get_personal_account(user_id)
        )
        return account.id if account is not None else None

    def _grouped(self, account_id: str, since: datetime, column) -> list[dict]:
        stmt = (
            select(
                column.label("key"),
                func.coalesce(func.sum(UsageRecord.cost_micros), 0).label("cost"),
                func.count().label("runs"),
                func.coalesce(func.sum(UsageRecord.quantity_units), 0).label("units"),
            )
            .where(UsageRecord.account_id == account_id, UsageRecord.created_at >= since)
            .group_by(column)
            .order_by(func.coalesce(func.sum(UsageRecord.cost_micros), 0).desc())
        )
        rows = self._session.execute(stmt).all()
        return [
            {
                "key": str(r.key or ""),
                "cost_micros": int(r.cost or 0),
                "cost_usd": micros_to_usd_str(int(r.cost or 0)),
                "runs": int(r.runs or 0),
                "units": int(r.units or 0),
            }
            for r in rows
        ]

    def summary(
        self, user_id: str, *, workspace_id: str | None = None, days: int = 30
    ) -> dict:
        """Return total spend + breakdowns by model, provider, stage, and day."""
        account_id = self._account_id(user_id, workspace_id)
        empty = {
            "scope": "workspace" if workspace_id else "user",
            "days": max(1, min(365, int(days))),
            "total_cost_micros": 0,
            "total_cost_usd": "0.00",
            "by_model": [],
            "by_provider": [],
            "by_stage": [],
            "by_day": [],
        }
        if account_id is None:
            return empty
        since = _since(days)

        total = int(
            self._session.execute(
                select(func.coalesce(func.sum(UsageRecord.cost_micros), 0)).where(
                    UsageRecord.account_id == account_id,
                    UsageRecord.created_at >= since,
                )
            ).scalar_one()
            or 0
        )
        return {
            **empty,
            "total_cost_micros": total,
            "total_cost_usd": micros_to_usd_str(total),
            "by_model": self._grouped(account_id, since, UsageRecord.model_id),
            "by_provider": self._grouped(account_id, since, UsageRecord.provider_key),
            "by_stage": self._grouped(account_id, since, UsageRecord.stage),
            "by_day": self._grouped(
                account_id, since, func.date(UsageRecord.created_at)
            ),
        }
