"""Remake-winner loop state: config validation + persistence on the batch anchor.

A "project" in the loop is a **batch** — the N variants one ``POST /jobs
{variants:N}`` request fanned out to (they share ``Job.batch_id``). The loop's
config and progress live on the batch's *anchor* job (its oldest row, soft-
deleted or not) inside ``Job.stages["_winner_loop"]``. That mirrors the existing
``_content_gate`` / ``_result_media`` pattern: no schema migration, and the JSON
blob is always replaced with a new dict (never mutated in place) so SQLAlchemy
detects the change.

A remake creates a new batch whose state points back to its ``parent_batch_id``
and to the ``root_batch_id`` of the lineage. The **spend cap** and the running
``spent_credits`` total are tracked on the root so the cap bounds the whole
chain of remakes, not each generation separately.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

LOOP_KEY = "_winner_loop"
LOOP_EVENT_STAGE = "winner_loop"
MODES: tuple[str, ...] = ("off", "manual", "auto")

DEFAULT_CHECK_AFTER_HOURS = 48
MIN_CHECK_AFTER_HOURS = 24
MAX_CHECK_AFTER_HOURS = 168
DEFAULT_MIN_VIEWS = 100
MAX_MIN_VIEWS = 100_000
MAX_SPEND_CAP_CREDITS = 1000
REMAKE_VARIANTS = 3
# After the first check, an inconclusive result is re-read every 24h up to this
# many times in total before the leader is settled as a low-confidence winner.
MAX_CHECKS = 4
RECHECK_HOURS = 24

# Terminal-for-this-generation statuses (no more publishing/measuring here).
SETTLED_STATUSES = frozenset({"winner_ready", "remaking", "remade", "cap_reached"})


class LoopConfigError(ValueError):
    """Invalid loop configuration supplied by the caller."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def default_spend_cap(job_cost: int) -> int:
    """Default cap: two automatic remakes (2 x 3 variants) at the current job cost."""
    return max(1, int(job_cost)) * REMAKE_VARIANTS * 2


def validate_config(
    *,
    mode: str,
    spend_cap_credits: int | None,
    check_after_hours: int | None,
    min_views: int | None,
    job_cost: int,
) -> dict:
    """Return a normalized config dict or raise :class:`LoopConfigError`."""
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in MODES:
        raise LoopConfigError(f"mode must be one of {list(MODES)}")
    cap = default_spend_cap(job_cost) if spend_cap_credits is None else int(spend_cap_credits)
    if cap < 0 or cap > MAX_SPEND_CAP_CREDITS:
        raise LoopConfigError(f"spend_cap_credits must be between 0 and {MAX_SPEND_CAP_CREDITS}")
    hours = DEFAULT_CHECK_AFTER_HOURS if check_after_hours is None else int(check_after_hours)
    if hours < MIN_CHECK_AFTER_HOURS or hours > MAX_CHECK_AFTER_HOURS:
        raise LoopConfigError(
            f"check_after_hours must be between {MIN_CHECK_AFTER_HOURS} and {MAX_CHECK_AFTER_HOURS}"
        )
    views = DEFAULT_MIN_VIEWS if min_views is None else int(min_views)
    if views < 0 or views > MAX_MIN_VIEWS:
        raise LoopConfigError(f"min_views must be between 0 and {MAX_MIN_VIEWS}")
    return {
        "mode": normalized_mode,
        "spend_cap_credits": cap,
        "check_after_hours": hours,
        "min_views": views,
    }


def read_state(job: Any) -> dict:
    """A defensive copy of the anchor job's loop state (``{}`` when unset)."""
    stages = getattr(job, "stages", None)
    raw = stages.get(LOOP_KEY) if isinstance(stages, dict) else None
    return dict(raw) if isinstance(raw, dict) else {}


def write_state(job: Any, state: dict) -> dict:
    """Replace the anchor's loop state with ``state`` (new dicts, never in place)."""
    new_state = {**state, "updated_at": iso(utcnow())}
    job.stages = {**(dict(job.stages) if isinstance(job.stages, dict) else {}), LOOP_KEY: new_state}
    return new_state


def new_state(
    *,
    batch_id: str,
    config: dict,
    platforms: list[str],
    root_batch_id: str = "",
    parent_batch_id: str = "",
    generation: int = 1,
) -> dict:
    """Initial state for a batch entering the loop."""
    now = iso(utcnow())
    root = root_batch_id or batch_id
    return {
        "version": 1,
        "batch_id": batch_id,
        "root_batch_id": root,
        "parent_batch_id": parent_batch_id,
        "generation": generation,
        **config,
        "platforms": list(platforms),
        "status": "awaiting_render",
        "note": "",
        "configured_at": now,
        "last_post_at": None,
        "check_due_at": None,
        "checks": 0,
        "last_checked_at": None,
        "variants": [],
        "ranking": None,
        "winner_job_id": "",
        "conclusive": False,
        "explanation": None,
        "remake_batch_id": "",
        "remake_job_ids": [],
        # Lineage totals — meaningful on the root batch only.
        "spent_credits": 0,
        "children": [],
    }


__all__ = [
    "DEFAULT_CHECK_AFTER_HOURS",
    "DEFAULT_MIN_VIEWS",
    "LOOP_EVENT_STAGE",
    "LOOP_KEY",
    "LoopConfigError",
    "MAX_CHECKS",
    "MODES",
    "RECHECK_HOURS",
    "REMAKE_VARIANTS",
    "SETTLED_STATUSES",
    "default_spend_cap",
    "iso",
    "new_state",
    "parse_iso",
    "read_state",
    "utcnow",
    "validate_config",
    "write_state",
]
