"""Usage metering + overage (Enterprise Billing Platform, Epic 3).

The metering layer records how much of each billable ``metric`` a workspace
consumes and compares it to the workspace's plan entitlement to compute overage.

Money-correctness invariants honored here:

* **No double-count.** :func:`record_usage` persists a :class:`MeteredUsage` row
  only when its ``idempotency_key`` is new; a replay of the same real-world event
  (same render job, same webhook) is a no-op that returns the existing row, so
  usage-based billing can never be gamed or inflated. The durable guard is the
  ``UNIQUE(idempotency_key)`` constraint enforced by
  :class:`~app.models.db.repositories.MeteredUsageRepository`.
* **Tenant-scoped.** Every aggregate filters strictly on ``workspace_id`` so a
  workspace's usage / overage can never include another tenant's rows.
* **Deterministic period.** The billing month (``'YYYY-MM'``) is derived from an
  injectable ``now`` so tests are deterministic; production callers omit it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services import entitlements

# --------------------------------------------------------------------------- #
# Metric catalogue + metric -> entitlement mapping (for overage).
# --------------------------------------------------------------------------- #
#: Billable metrics. ``render`` = one rendered video (the primary unit that maps
#: to a credit); ``api_call`` = one authenticated public-API request.
METRIC_RENDER: str = "render"
METRIC_API_CALL: str = "api_call"

#: Which plan entitlement bounds each metric for overage. A metric absent from
#: this map has NO plan limit — its overage is always 0 (unbounded / not billed
#: as overage). ``render`` is bounded by the plan's monthly credit allotment.
METRIC_ENTITLEMENT: dict[str, str] = {
    METRIC_RENDER: entitlements.FEAT_MONTHLY_CREDITS,
}


@dataclass(frozen=True)
class UsageResult:
    """Outcome of a :func:`record_usage` call.

    ``created`` is ``True`` only on the first insert for the idempotency key; a
    replayed event returns the existing row with ``created=False`` (nothing was
    added), which is how a caller confirms an event was counted exactly once.
    """

    workspace_id: str
    metric: str
    quantity: int
    period_ym: str
    idempotency_key: str
    created: bool


@dataclass(frozen=True)
class MetricOverage:
    """Per-metric overage for a billing period: usage vs plan limit."""

    metric: str
    used: int
    limit: int | None  # None == the metric is unbounded for this plan
    overage: int  # max(0, used - limit); 0 when unbounded


def current_period_ym(now: datetime | None = None) -> str:
    """Return the billing month as a ``'YYYY-MM'`` token (injectable ``now``)."""
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m")


def record_usage(
    session: Any,
    workspace_id: str,
    metric: str,
    quantity: int,
    idempotency_key: str,
    *,
    now: datetime | None = None,
) -> UsageResult:
    """Record ``quantity`` units of ``metric`` for a workspace — exactly once.

    Inserts a :class:`MeteredUsage` row only when ``idempotency_key`` is new; a
    replay of the same key inserts NOTHING and returns the already-counted row
    (``created=False``) so usage is never double-counted. ``quantity`` is floored
    non-negative and ``metric`` lower-cased at the repository boundary. The
    billing month is derived from ``now`` (injectable for deterministic tests).
    Raises ``ValueError`` on a blank ``workspace_id`` / ``metric`` /
    ``idempotency_key``.
    """
    from app.models.db.repositories import MeteredUsageRepository

    period_ym = current_period_ym(now)
    row, created = MeteredUsageRepository(session).record(
        workspace_id=workspace_id,
        metric=metric,
        quantity=quantity,
        period_ym=period_ym,
        idempotency_key=idempotency_key,
    )
    return UsageResult(
        workspace_id=row.workspace_id,
        metric=row.metric,
        quantity=int(row.quantity),
        period_ym=row.period_ym,
        idempotency_key=row.idempotency_key,
        created=created,
    )


def aggregate_usage(
    session: Any, workspace_id: str, period_ym: str
) -> dict[str, int]:
    """Return per-metric total usage for a workspace's billing month.

    Tenant-scoped ``{metric: total}`` (empty when there is no usage). A blank
    ``workspace_id`` / ``period_ym`` yields an empty mapping.
    """
    from app.models.db.repositories import MeteredUsageRepository

    return MeteredUsageRepository(session).aggregate_for_period(
        workspace_id, period_ym
    )


def overage_for(
    session: Any, workspace_id: str, period_ym: str
) -> dict[str, MetricOverage]:
    """Return per-metric overage (usage beyond the plan limit) for the period.

    For each metric the workspace used, compares the aggregate usage to the
    plan's entitlement limit (resolved via :mod:`app.services.entitlements`, which
    falls back to the base/free plan for a workspace with no LIVE subscription).
    A metric with no plan limit (absent from :data:`METRIC_ENTITLEMENT`) is
    reported with ``limit=None`` and ``overage=0``. ``overage`` is
    ``max(0, used - limit)`` so a workspace within its allotment shows zero.
    """
    usage = aggregate_usage(session, workspace_id, period_ym)
    result: dict[str, MetricOverage] = {}
    for metric, used in usage.items():
        feature = METRIC_ENTITLEMENT.get(metric)
        if feature is None:
            result[metric] = MetricOverage(
                metric=metric, used=used, limit=None, overage=0
            )
            continue
        raw_limit = entitlements.entitlement_value(
            session, workspace_id, feature, default=0
        )
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 0
        result[metric] = MetricOverage(
            metric=metric,
            used=used,
            limit=limit,
            overage=max(0, used - limit),
        )
    return result


__all__ = [
    "METRIC_API_CALL",
    "METRIC_ENTITLEMENT",
    "METRIC_RENDER",
    "MetricOverage",
    "UsageResult",
    "aggregate_usage",
    "current_period_ym",
    "overage_for",
    "record_usage",
]
