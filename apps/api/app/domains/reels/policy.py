"""Pricing, rate, fan-out, and retry policy for reel jobs.

M3.1 (one public pricing model, MD8): credits by style and length come from
:mod:`app.domains.reels.pricing` (MG3) through :func:`job_credits`; presenter
reels are Pro and Agency only with a monthly cap; charge on keep is behind
``MENIVOR_CHARGE_ON_KEEP``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import config

DEFAULT_JOB_KIND = "avatar_reel"
JOB_DEBIT_REASON = "job_debit"
JOB_REFUND_REASON = "refund"
DEFAULT_JOB_COST = 1
MAX_VARIANTS = 3
DEFAULT_JOBS_RATE_LIMIT = 30
DEFAULT_JOBS_RATE_WINDOW_S = 3600
DEFAULT_BROLL_RATE_LIMIT = 20
DEFAULT_BROLL_RATE_WINDOW_S = 3600


def job_cost() -> int:
    return int(config.app.get("reelforge_job_cost", DEFAULT_JOB_COST))


# --------------------------------------------------------------------------- #
# One public pricing model (M3.1, MD8). Credits by style and length come from
# the MG3 table (app.domains.reels.pricing); this module owns the plan rules.
# --------------------------------------------------------------------------- #
#: Standard credits per presenter reel (MD8), ``MENIVOR_PRESENTER_CREDITS``.
DEFAULT_PRESENTER_CREDITS = 5
#: Personal plans that include presenter reels (MD8: Pro and up).
PRESENTER_PLANS: frozenset[str] = frozenset({"pro", "agency"})
#: Presenter reels per calendar month per user, ``MENIVOR_PRESENTER_MONTHLY_CAP``.
#: Not fixed by MD8; 30 is the working default until the owner sets it.
DEFAULT_PRESENTER_MONTHLY_CAP = 30


def presenter_credits() -> int:
    """Standard credits one presenter reel costs (MD8 default 5)."""
    return _env_int("MENIVOR_PRESENTER_CREDITS", DEFAULT_PRESENTER_CREDITS)


def presenter_monthly_cap() -> int:
    return _env_int("MENIVOR_PRESENTER_MONTHLY_CAP", DEFAULT_PRESENTER_MONTHLY_CAP)


def job_credits(params: Any) -> int:
    """Standard credits ONE job of ``params`` costs (see ``pricing.standard_line``).

    1 credit per reel up to 60 s, 1 per started minute for long-form, and
    ``presenter_credits()`` for a presenter reel (whichever is higher), all
    scaled by the ``reelforge_job_cost`` knob.
    """
    from app.domains.reels import pricing

    return pricing.standard_line(params).credits


def presenter_plan(session: Any, user_id: str) -> str:
    """The caller's live personal plan key when it includes presenters, else ``""``."""
    from app.services.billing import creator_subscriptions as subs

    try:
        row = subs._row(session, str(user_id))
    except Exception:  # noqa: BLE001 - unknown plan never unlocks a paid SKU
        return ""
    if not subs.is_live(row):
        return ""
    key = str(getattr(row, "plan_key", "") or "").strip().lower()
    return key if key in PRESENTER_PLANS else ""


#: Ledger reasons that return a job's standard credits (see ``reels/refunds.py``).
REFUND_REASONS: frozenset[str] = frozenset({JOB_REFUND_REASON, "cancel_refund", "failure_refund"})


def _refunded_job_ids(session: Any, job_ids: list[str]) -> set[str]:
    """Jobs whose newest credit-ledger row is a refund (the render was given back)."""
    if not job_ids:
        return set()
    from sqlalchemy import func, select

    from app.models.db.models import CreditLedger

    newest = (
        select(CreditLedger.job_id, func.max(CreditLedger.id).label("last_id"))
        .where(CreditLedger.job_id.in_(job_ids))
        .group_by(CreditLedger.job_id)
        .subquery()
    )
    rows = session.execute(
        select(CreditLedger.job_id)
        .join(newest, CreditLedger.id == newest.c.last_id)
        .where(CreditLedger.delta > 0, CreditLedger.reason.in_(sorted(REFUND_REASONS)))
    ).scalars()
    return {str(r) for r in rows}


def presenter_reels_this_month(session: Any, user_id: str, now: Any = None) -> int:
    """Presenter reels ``user_id`` started this calendar month (UTC).

    Refunded renders do not count (Wave D hand-off H3): a job that failed, or
    whose newest ledger row is a refund (failure, cancel), gave the reel back.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models import const
    from app.models.db.models import Job

    clock = now or datetime.now(timezone.utc)
    start = clock.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    rows = session.execute(
        select(Job.id, Job.params, Job.state).where(
            Job.user_id == str(user_id), Job.created_at >= start
        )
    ).all()
    presenter = [
        (str(job_id), state)
        for job_id, params, state in rows
        if isinstance(params, dict) and str(params.get("layout") or "") not in ("", "captions_only")
    ]
    refunded = _refunded_job_ids(session, [job_id for job_id, _ in presenter])
    return sum(
        1
        for job_id, state in presenter
        if state != const.TASK_STATE_FAILED and job_id not in refunded
    )


def render_credits(params: Any) -> int:
    """Standard credits one render of ``params`` costs (object or stored dict).

    The per-SKU price from ``reels/pricing.py`` (by length, presenter floor),
    never below the flat per-reel knob. Series, Autopilot and the winner loop
    price through this, like a create (H3).
    """
    if isinstance(params, dict):
        from types import SimpleNamespace

        params = SimpleNamespace(**params)
    return max(int(job_cost()), int(job_credits(params)), 1)


def require_presenter_allowed(session: Any, user_id: str, params: Any, count: int = 1) -> None:
    """Refuse a presenter reel below Pro or past the monthly cap (402 ``sku_locked``)."""
    from app.domains.reels import pricing

    if not pricing.wants_presenter(params):
        return
    if not presenter_plan(session, user_id):
        raise pricing.SkuLocked(
            pricing.SKU_PRESENTER, "AI presenter reels are part of the Pro and Agency plans"
        )
    used = presenter_reels_this_month(session, user_id)
    cap = presenter_monthly_cap()
    if used + max(1, int(count)) > cap:
        raise pricing.SkuLocked(
            pricing.SKU_PRESENTER,
            f"this month's {cap} presenter reels are used; more open on the 1st",
        )


# --------------------------------------------------------------------------- #
# Charge on keep (M3.1): with ``MENIVOR_CHARGE_ON_KEEP`` on, variant 1 of a
# create is debited at create and variants 2-3 only when kept (downloaded or
# posted) through ``POST /jobs/{id}/keep`` (app.domains.reels.keep).
# --------------------------------------------------------------------------- #
def charge_on_keep_enabled() -> bool:
    import os

    return os.environ.get("MENIVOR_CHARGE_ON_KEEP", "").strip().lower() not in _OFF


def jobs_rate_limit() -> int:
    return int(config.app.get("reelforge_jobs_rate_limit", DEFAULT_JOBS_RATE_LIMIT))


def jobs_rate_window_s() -> int:
    return int(
        config.app.get("reelforge_jobs_rate_window_s", DEFAULT_JOBS_RATE_WINDOW_S)
    )


def broll_rate_limit() -> int:
    return int(config.app.get("reelforge_broll_rate_limit", DEFAULT_BROLL_RATE_LIMIT))


def broll_rate_window_s() -> int:
    return int(
        config.app.get("reelforge_broll_rate_window_s", DEFAULT_BROLL_RATE_WINDOW_S)
    )


def resolve_variants(body: Any) -> int:
    """Clamp a top-level or nested variant request to the supported fan-out."""
    raw = getattr(body, "variants", None)
    if raw is None:
        params = getattr(body, "params", None)
        if hasattr(params, "model_dump"):
            params = params.model_dump()
        if isinstance(params, dict):
            raw = params.get("variants")
    if raw is None:
        return 1
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, min(MAX_VARIANTS, count))


# --------------------------------------------------------------------------- #
# Render lanes (M1.3). One Celery queue per lane, highest first; a worker that
# consumes them in this order (strict priority, not round robin) always takes
# the most important waiting render. Message priority is not used: it is
# unreliable on the Redis broker.
# --------------------------------------------------------------------------- #
LANE_PAID = "paid"
LANE_FIRST = "first"
LANE_FREE = "free"
LANE_VARIANTS = "variants"
LANE_BULK = "bulk"
LANES: tuple[str, ...] = (LANE_PAID, LANE_FIRST, LANE_FREE, LANE_VARIANTS, LANE_BULK)
#: The paid lane keeps the historical ``render`` queue name, so a worker that
#: still consumes only ``render`` keeps serving paid first renders.
LANE_QUEUES: dict[str, str] = {
    LANE_PAID: "render",
    LANE_FIRST: "render_first",
    LANE_FREE: "render_free",
    LANE_VARIANTS: "render_low",
    LANE_BULK: "render_bulk",
}
DEFAULT_RENDER_QUEUE = "render"
_OFF = frozenset({"", "0", "off", "false", "no"})


def lanes_enabled() -> bool:
    """``MENIVOR_RENDER_LANES`` (default off until workers consume every lane queue)."""
    import os

    return os.environ.get("MENIVOR_RENDER_LANES", "").strip().lower() not in _OFF


def render_lane(*, paid: bool, first_reel: bool, variant_index: int, bulk: bool = False) -> str:
    """The lane for one render: paid > first reel > free > variants 2-3 > bulk.

    Variant 1 of every create renders in its owner's lane; variants 2 and 3
    (and later Autopilot items of one run) wait in the variants lane, so every
    creator's first result comes before anyone's extra variants. Dogfood and
    sample renders are bulk.
    """
    if bulk:
        return LANE_BULK
    if int(variant_index or 0) > 0:
        return LANE_VARIANTS
    if paid:
        return LANE_PAID
    if first_reel:
        return LANE_FIRST
    return LANE_FREE


def lane_rank(lane: str) -> int:
    """0 for the highest lane; unknown lanes rank with free."""
    return LANES.index(lane) if lane in LANES else LANES.index(LANE_FREE)


def lane_queue(lane: str) -> str:
    """The Celery queue for ``lane`` (``render`` for all when lanes are off)."""
    if not lanes_enabled():
        return DEFAULT_RENDER_QUEUE
    return LANE_QUEUES.get(lane, LANE_QUEUES[LANE_FREE])


def worker_queue_order() -> str:
    """The ``-Q`` value for a render worker, highest lane first."""
    return ",".join(LANE_QUEUES[lane] for lane in LANES)


# --------------------------------------------------------------------------- #
# Fair share (M1.3 amendment): per-user and per-API-key concurrent renders and
# a daily cap tied to the plan, so one big buyer cannot fill every slot.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FairShare:
    """Render caps for one plan."""

    concurrent: int  # unfinished renders at once (per user)
    daily: int  # renders started per rolling 24 h (per user)


#: Plan key -> caps. ``free`` covers signup credits; ``pack`` and ``pro``
#: (RevenueCat) are pay-as-you-go buyers. Env overrides per plan:
#: ``MENIVOR_FAIR_<PLAN>_CONCURRENT`` / ``MENIVOR_FAIR_<PLAN>_DAILY``.
FAIR_SHARE: dict[str, FairShare] = {
    "free": FairShare(concurrent=3, daily=9),
    "pack": FairShare(concurrent=3, daily=60),
    "pro": FairShare(concurrent=4, daily=100),
    "creator": FairShare(concurrent=3, daily=40),
    "agency": FairShare(concurrent=6, daily=300),
}
DEFAULT_API_KEY_CONCURRENT = 3
DEFAULT_GLOBAL_QUEUE_CAP = 60


def _env_int(name: str, default: int) -> int:
    import os

    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def fair_share(plan: str) -> FairShare:
    """Caps for ``plan`` (unknown plans get the free caps)."""
    key = str(plan or "free").strip().lower()
    base = FAIR_SHARE.get(key, FAIR_SHARE["free"])
    tag = key.upper() if key in FAIR_SHARE else "FREE"
    return FairShare(
        concurrent=_env_int(f"MENIVOR_FAIR_{tag}_CONCURRENT", base.concurrent),
        daily=_env_int(f"MENIVOR_FAIR_{tag}_DAILY", base.daily),
    )


def api_key_concurrent_cap() -> int:
    """Unfinished renders one API key may hold (``MENIVOR_API_KEY_CONCURRENT``)."""
    return _env_int("MENIVOR_API_KEY_CONCURRENT", DEFAULT_API_KEY_CONCURRENT)


def global_queue_cap() -> int:
    """Unfinished renders across everyone before new creates get 429 (``MENIVOR_QUEUE_CAP``)."""
    return _env_int("MENIVOR_QUEUE_CAP", DEFAULT_GLOBAL_QUEUE_CAP)


def is_retryable_kind(kind: str) -> bool:
    """Return whether canonical ``POST /jobs/{id}/retry`` supports ``kind``."""
    return str(kind or "") in {DEFAULT_JOB_KIND, "editor_export"}


__all__ = [
    "DEFAULT_PRESENTER_CREDITS",
    "DEFAULT_PRESENTER_MONTHLY_CAP",
    "PRESENTER_PLANS",
    "charge_on_keep_enabled",
    "job_credits",
    "presenter_credits",
    "presenter_monthly_cap",
    "presenter_plan",
    "presenter_reels_this_month",
    "render_credits",
    "require_presenter_allowed",
    "DEFAULT_API_KEY_CONCURRENT",
    "DEFAULT_GLOBAL_QUEUE_CAP",
    "DEFAULT_RENDER_QUEUE",
    "FAIR_SHARE",
    "LANES",
    "LANE_BULK",
    "LANE_FIRST",
    "LANE_FREE",
    "LANE_PAID",
    "LANE_QUEUES",
    "LANE_VARIANTS",
    "FairShare",
    "api_key_concurrent_cap",
    "fair_share",
    "global_queue_cap",
    "lane_queue",
    "lane_rank",
    "lanes_enabled",
    "render_lane",
    "worker_queue_order",
    "DEFAULT_BROLL_RATE_LIMIT",
    "DEFAULT_BROLL_RATE_WINDOW_S",
    "DEFAULT_JOB_COST",
    "DEFAULT_JOB_KIND",
    "DEFAULT_JOBS_RATE_LIMIT",
    "DEFAULT_JOBS_RATE_WINDOW_S",
    "JOB_DEBIT_REASON",
    "JOB_REFUND_REASON",
    "MAX_VARIANTS",
    "broll_rate_limit",
    "broll_rate_window_s",
    "is_retryable_kind",
    "job_cost",
    "jobs_rate_limit",
    "jobs_rate_window_s",
    "resolve_variants",
]
