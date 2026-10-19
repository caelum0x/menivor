"""Hook Performance Loop — self-reported outcome logging + win-score ranking.

After a creator renders a :class:`~app.models.db.models.Job` and posts it to
TikTok / Instagram / YouTube, they LOG the metrics that reel actually earned
(views, likes, comments, shares, saves and watch-through/retention). This module
persists one outcome row per job (:func:`log_performance`) and aggregates those
outcomes per HOOK and per TEMPLATE into a deterministic "win score"
(:func:`winning_hooks` / :func:`winning_templates`) — the signal the SPARK idea
engine biases toward so it re-suggests patterns that genuinely convert.

Fully key-free: every metric is creator-entered — there is no external platform
API involved.

Design rules (mirroring :mod:`app.services.insights` / :mod:`app.services.analytics`):

* **Strictly per-user.** :func:`log_performance` verifies the job belongs to the
  caller BEFORE any write; every aggregate filters on ``jobs.user_id`` so a
  creator can never log against — or read the outcomes of — another creator's
  job. There is no cross-user code path.
* **Read-only aggregates.** The ``winning_*`` functions never mutate; the caller
  owns the transaction.
* **Deterministic + guarded.** The win score is a pure, documented function of
  the aggregated metrics (see :data:`WIN_SCORE_ENGAGEMENT_WEIGHT` /
  :data:`WIN_SCORE_RETENTION_WEIGHT`). Divide-by-zero is guarded (a 0-view group
  yields an engagement rate of 0, never ``NaN``/``Inf``), a group with no logged
  reels simply never appears, and ties are broken by label so the ranking is
  stable.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db.models import Job, JobPerformance

# --------------------------------------------------------------------------- #
# Grouping-key derivation (mirrors app.services.analytics conventions)
# --------------------------------------------------------------------------- #
#: ``Job.params`` keys probed (best-effort, in priority order) for a template
#: hint. Kept in sync with :mod:`app.services.analytics`.
_TEMPLATE_KEYS: tuple[str, ...] = ("template", "template_id", "template_name")

#: ``Job.params`` key holding the creator's subject/hook line.
_HOOK_KEY = "video_subject"


# --------------------------------------------------------------------------- #
# Win-score tunables (documented, deterministic)
# --------------------------------------------------------------------------- #
#: The win score blends two normalized signals, each in ``[0, 1]``:
#:
#:   engagement_rate = (likes + comments + shares + saves) / max(views, 1)
#:   retention_frac  = mean(retention_pct) / 100
#:
#: as ``win_score = SCALE * (ENGAGEMENT_WEIGHT * min(engagement_rate, 1) +
#: RETENTION_WEIGHT * retention_frac)``. The weights sum to 1 so the score lands
#: in ``[0, SCALE]``; ``engagement_rate`` is capped at 1 (a reel can, rarely,
#: earn more saves+likes than views) so a single viral outlier cannot dominate
#: the blend. ``max(views, 1)`` is the divide-by-zero guard: a 0-view group
#: scores 0 on the engagement term instead of ``NaN``/``Inf``.
WIN_SCORE_ENGAGEMENT_WEIGHT: float = 0.6
WIN_SCORE_RETENTION_WEIGHT: float = 0.4
#: Scale the ``[0, 1]`` blend onto a friendlier ``[0, 100]`` points range.
WIN_SCORE_SCALE: float = 100.0
#: Decimal places the emitted ``win_score`` is rounded to (keeps the value
#: deterministic and JSON-clean across SQLite/Postgres).
WIN_SCORE_ROUND: int = 4

#: Clamp for the ``limit`` a ``winning_*`` ranking may return, so an untrusted
#: value can never request an unbounded result.
WINNERS_MIN_LIMIT = 1
WINNERS_MAX_LIMIT = 100
WINNERS_DEFAULT_LIMIT = 10


def _clamp_limit(limit: int) -> int:
    """Clamp a requested ranking size into ``[1, 100]`` (default on garbage)."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return WINNERS_DEFAULT_LIMIT
    return max(WINNERS_MIN_LIMIT, min(value, WINNERS_MAX_LIMIT))


def _hook_of(params: dict[str, Any], script: Any) -> Optional[str]:
    """Best-effort hook line for a job: the subject param, else the script head.

    Returns ``None`` when neither a subject param nor a script line can be
    recovered, so a job with no identifiable hook contributes nothing to the
    ranking (never a phantom empty group).
    """
    subject = params.get(_HOOK_KEY)
    if isinstance(subject, str) and subject.strip():
        return subject.strip()
    if isinstance(script, str) and script.strip():
        for line in script.splitlines():
            if line.strip():
                return line.strip()
    return None


def _template_of(params: dict[str, Any]) -> Optional[str]:
    """Best-effort template hint for a job from its ``params`` (or ``None``)."""
    for key in _TEMPLATE_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class _Group:
    """A mutable per-key accumulator of a creator's logged reel outcomes."""

    __slots__ = ("reels", "views", "engagements", "retention_sum")

    def __init__(self) -> None:
        self.reels = 0
        self.views = 0
        self.engagements = 0
        self.retention_sum = 0.0

    def add(self, perf: JobPerformance) -> None:
        """Fold one performance row into the running totals (clamped defensively)."""
        self.reels += 1
        self.views += max(0, int(perf.views or 0))
        self.engagements += (
            max(0, int(perf.likes or 0))
            + max(0, int(perf.comments or 0))
            + max(0, int(perf.shares or 0))
            + max(0, int(perf.saves or 0))
        )
        self.retention_sum += max(0.0, min(100.0, float(perf.retention_pct or 0.0)))

    def win_score(self) -> float:
        """Deterministic ``[0, WIN_SCORE_SCALE]`` win score for this group.

        Guards divide-by-zero via ``max(views, 1)``; a group with no reels (never
        constructed in practice) yields 0 rather than ``NaN``.
        """
        if self.reels <= 0:
            return 0.0
        engagement_rate = min(self.engagements / max(self.views, 1), 1.0)
        retention_frac = min(max((self.retention_sum / self.reels) / 100.0, 0.0), 1.0)
        blended = (
            WIN_SCORE_ENGAGEMENT_WEIGHT * engagement_rate
            + WIN_SCORE_RETENTION_WEIGHT * retention_frac
        )
        return round(WIN_SCORE_SCALE * blended, WIN_SCORE_ROUND)

    def avg_retention_pct(self) -> float:
        """Mean self-reported retention across the group's reels (0 when empty)."""
        if self.reels <= 0:
            return 0.0
        return round(self.retention_sum / self.reels, WIN_SCORE_ROUND)


# --------------------------------------------------------------------------- #
# Logging (write path)
# --------------------------------------------------------------------------- #
def log_performance(
    session: Session,
    user_id: str,
    job_id: str,
    metrics: dict | None = None,
) -> JobPerformance:
    """Log (idempotent-upsert) the real-world outcome of the caller's own reel.

    Ownership is verified BEFORE any write: the job is loaded and its
    ``user_id`` compared to the caller. This is the single choke point that keeps
    the loop strictly per-user.

    Args:
        session: An active SQLAlchemy session (the caller owns the transaction).
        user_id: The creator logging the outcome (the resolved caller).
        job_id: The creator's own job whose posted reel earned the metrics.
        metrics: Creator-entered outcome dict — any of ``platform``, ``views``,
            ``likes``, ``comments``, ``shares``, ``saves``, ``retention_pct``.
            Each value is validated/clamped at the repository boundary.

    Returns:
        The upserted :class:`JobPerformance` row (one per job — re-logging
        updates it in place).

    Raises:
        ValueError: If ``user_id`` / ``job_id`` is blank, or the job does not
            exist.
        PermissionError: If the job exists but belongs to a different user.
    """
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id is required")
    if not job_id or not str(job_id).strip():
        raise ValueError("job_id is required")

    job = session.get(Job, str(job_id).strip())
    if job is None:
        raise ValueError(f"job not found: {job_id}")
    if job.user_id != user_id:
        # Never leak existence details across users beyond the ownership fact.
        raise PermissionError("job does not belong to the requesting user")

    # Import here to avoid a module-level cycle (repositories import models,
    # services import repositories) and to keep the write path explicit.
    from app.models.db.repositories import JobPerformanceRepository

    return JobPerformanceRepository(session).upsert(
        job_id=job.id, user_id=user_id, metrics=metrics or {}
    )


# --------------------------------------------------------------------------- #
# Ranking (read path)
# --------------------------------------------------------------------------- #
def _ranked_groups(
    session: Session,
    user_id: str,
    key_fn,
    key_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Aggregate the user's logged outcomes by a derived key and rank by win score.

    ``key_fn(params, script)`` returns the grouping label (hook/template) or
    ``None`` to drop the job. Results are sorted by ``win_score`` descending with
    a label ascending tie-break, so the ranking is fully deterministic, then
    truncated to ``limit``.
    """
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id is required")
    capped = _clamp_limit(limit)

    # Strictly owner-scoped: join performance rows to their jobs and filter on
    # the job owner (JobPerformance.user_id is also the owner, checked for
    # defense-in-depth) so no other creator's outcomes are ever aggregated.
    stmt = (
        select(JobPerformance, Job.params, Job.script)
        .join(Job, JobPerformance.job_id == Job.id)
        .where(
            Job.user_id == user_id,
            JobPerformance.user_id == user_id,
        )
    )

    groups: dict[str, _Group] = defaultdict(_Group)
    for perf, params, script in session.execute(stmt).all():
        blob = params if isinstance(params, dict) else {}
        label = key_fn(blob, script)
        if not label:
            continue  # a job with no identifiable hook/template contributes nothing
        groups[label].add(perf)

    ranked = sorted(
        groups.items(),
        key=lambda item: (-item[1].win_score(), item[0]),
    )
    return [
        {
            key_name: label,
            "win_score": group.win_score(),
            "reels": group.reels,
            "views": group.views,
            "engagements": group.engagements,
            "avg_retention_pct": group.avg_retention_pct(),
        }
        for label, group in ranked[:capped]
    ]


def _hook_key(params: dict[str, Any], script: Any) -> Optional[str]:
    """Grouping key for :func:`winning_hooks`."""
    return _hook_of(params, script)


def _template_key(params: dict[str, Any], _script: Any) -> Optional[str]:
    """Grouping key for :func:`winning_templates` (ignores the script)."""
    return _template_of(params)


def winning_hooks(
    session: Session, user_id: str, limit: int = WINNERS_DEFAULT_LIMIT
) -> list[dict[str, Any]]:
    """Rank the creator's hooks by aggregated, self-reported win score.

    Groups the user's logged reel outcomes by each job's hook (the
    ``video_subject`` param, else the first line of ``Job.script``), computes a
    deterministic :data:`win score <WIN_SCORE_ENGAGEMENT_WEIGHT>` per hook, and
    returns the ``limit`` best (ties broken by hook text).

    Args:
        session: An active SQLAlchemy session (read-only; not committed here).
        user_id: The creator whose hooks to rank (strictly scoped).
        limit: Max entries to return (clamped to ``[1, 100]``).

    Returns:
        ``[{"hook", "win_score", "reels", "views", "engagements",
        "avg_retention_pct"}, ...]`` ordered best-first.

    Raises:
        ValueError: If ``user_id`` is empty/blank.
    """
    return _ranked_groups(session, user_id, _hook_key, "hook", limit)


def winning_templates(
    session: Session, user_id: str, limit: int = WINNERS_DEFAULT_LIMIT
) -> list[dict[str, Any]]:
    """Rank the creator's templates by aggregated, self-reported win score.

    Groups the user's logged reel outcomes by each job's template hint (a
    ``template`` / ``template_id`` / ``template_name`` param), computes a
    deterministic :data:`win score <WIN_SCORE_ENGAGEMENT_WEIGHT>` per template,
    and returns the ``limit`` best (ties broken by template label).

    Args:
        session: An active SQLAlchemy session (read-only; not committed here).
        user_id: The creator whose templates to rank (strictly scoped).
        limit: Max entries to return (clamped to ``[1, 100]``).

    Returns:
        ``[{"template", "win_score", "reels", "views", "engagements",
        "avg_retention_pct"}, ...]`` ordered best-first.

    Raises:
        ValueError: If ``user_id`` is empty/blank.
    """
    return _ranked_groups(session, user_id, _template_key, "template", limit)


__all__ = [
    "log_performance",
    "winning_hooks",
    "winning_templates",
    "WIN_SCORE_ENGAGEMENT_WEIGHT",
    "WIN_SCORE_RETENTION_WEIGHT",
    "WIN_SCORE_SCALE",
]
