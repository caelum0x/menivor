"""Read models for the Insights winner-loop UI: board, project detail, timeline.

All reads are owner-scoped (every query filters on the caller's ``user_id``) and
only expose the creator's own jobs, loop state and publish audit rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.models import const

from .winner_loop_service import LoopNotFound, find_anchor
from .winner_loop_state import LOOP_EVENT_STAGE, REMAKE_VARIANTS, iso, read_state

_BOARD_LOOKBACK = timedelta(days=60)
_BOARD_JOB_LIMIT = 600
_TIMELINE_LIMIT = 200
_PUBLISH_EVENT_STATUSES = ("native_published", "native_failed", "native_held")
_STATE_LABELS = {
    const.TASK_STATE_COMPLETE: "complete",
    const.TASK_STATE_FAILED: "failed",
    const.TASK_STATE_PROCESSING: "rendering",
}


def _title(job: Any) -> str:
    params = job.params if isinstance(job.params, dict) else {}
    return str(getattr(job, "title", "") or params.get("video_subject") or "Untitled project")[:200]


def _costs() -> tuple[int, int]:
    from app.domains.reels.policy import job_cost

    cost = job_cost()
    return cost, cost * REMAKE_VARIANTS


def _publishing_open() -> bool:
    try:
        from app.core.launch.policy import publishing_enabled

        return bool(publishing_enabled())
    except Exception:  # noqa: BLE001 - reads as closed
        return False


def _summary(batch_id: str, state: dict, jobs: list, title: str) -> dict:
    ranking = state.get("ranking") or {}
    variants = {v.get("job_id"): v for v in state.get("variants") or [] if isinstance(v, dict)}
    winner_id = str(state.get("winner_job_id") or "")
    winner = variants.get(winner_id, {})
    explanation = state.get("explanation") or {}
    return {
        "batch_id": batch_id,
        "title": title,
        "generation": int(state.get("generation", 1) or 1),
        "root_batch_id": state.get("root_batch_id") or batch_id,
        "parent_batch_id": state.get("parent_batch_id") or "",
        "mode": state.get("mode", "off"),
        "status": state.get("status", ""),
        "note": state.get("note", ""),
        "platforms": list(state.get("platforms") or []),
        "variant_count": len(jobs),
        "check_due_at": state.get("check_due_at"),
        "last_checked_at": state.get("last_checked_at"),
        "winner_job_id": winner_id,
        "winner_hook": winner.get("hook", ""),
        "winner_views": winner.get("views"),
        "winner_avg_watch_frac": winner.get("avg_watch_frac"),
        "winner_engagement_rate": winner.get("engagement_rate"),
        "conclusive": bool(state.get("conclusive")),
        "headline": explanation.get("headline", "") if winner_id else "",
        "confidence": explanation.get("confidence", "none") if winner_id else "none",
        "leader_job_id": ranking.get("winner_job_id", "") if ranking else "",
        "remake_batch_id": state.get("remake_batch_id", ""),
        "updated_at": state.get("updated_at"),
    }


def loop_board(session: Any, user_id: str, now: datetime) -> dict:
    """Winners board + every loop-enabled project + recent projects that could join."""
    from app.models.db.models import Job

    jobs = session.execute(
        select(Job)
        .where(
            Job.user_id == user_id,
            Job.batch_id.isnot(None),
            Job.deleted_at.is_(None),
            Job.created_at >= now - _BOARD_LOOKBACK,
        )
        .order_by(Job.created_at.desc())
        .limit(_BOARD_JOB_LIMIT)
    ).scalars().all()
    by_batch: dict[str, list] = {}
    for job in jobs:
        by_batch.setdefault(str(job.batch_id), []).append(job)

    loops: list[dict] = []
    candidates: list[dict] = []
    for batch_id, batch_jobs in by_batch.items():
        ordered = sorted(batch_jobs, key=lambda j: (j.created_at, j.id))
        state = next((read_state(j) for j in ordered if read_state(j)), {})
        title = _title(ordered[0])
        if state:
            loops.append(_summary(batch_id, state, ordered, title))
        elif len(ordered) >= 2:
            candidates.append({
                "batch_id": batch_id,
                "title": title,
                "variant_count": len(ordered),
                "complete_count": sum(1 for j in ordered if j.state == const.TASK_STATE_COMPLETE),
                "created_at": iso(ordered[0].created_at),
            })
    loops.sort(key=lambda s: str(s.get("updated_at") or ""), reverse=True)
    winners = sorted(
        (s for s in loops if s["winner_job_id"]),
        key=lambda s: str(s.get("last_checked_at") or ""),
        reverse=True,
    )
    job_cost, remake_cost = _costs()
    return {
        "winners": winners,
        "loops": loops,
        "candidates": candidates[:30],
        "publishing_enabled": _publishing_open(),
        "job_cost_credits": job_cost,
        "remake_cost_credits": remake_cost,
    }


def _timeline(session: Any, anchor_ids: dict[str, str], publish_job_ids: dict[str, str]) -> list[dict]:
    """Loop events across the lineage + native publish events of this project."""
    from app.models.db.models import JobEvent

    items: list[dict] = []
    if anchor_ids:
        rows = session.execute(
            select(JobEvent)
            .where(JobEvent.job_id.in_(list(anchor_ids)), JobEvent.stage == LOOP_EVENT_STAGE)
            .order_by(JobEvent.id.desc())
            .limit(_TIMELINE_LIMIT)
        ).scalars().all()
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            items.append({
                "at": iso(row.created_at),
                "kind": row.status,
                "message": row.message or "",
                "batch_id": anchor_ids.get(row.job_id, ""),
                "job_id": str(payload.get("job_id") or payload.get("winner_job_id") or ""),
                "platform": str(payload.get("platform") or ""),
                "url": "",
            })
    if publish_job_ids:
        rows = session.execute(
            select(JobEvent)
            .where(
                JobEvent.job_id.in_(list(publish_job_ids)),
                JobEvent.stage == "publish",
                JobEvent.status.in_(_PUBLISH_EVENT_STATUSES),
            )
            .order_by(JobEvent.id.desc())
            .limit(_TIMELINE_LIMIT)
        ).scalars().all()
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            items.append({
                "at": iso(row.created_at),
                "kind": str(row.status).replace("native_", ""),
                "message": row.message or "",
                "batch_id": publish_job_ids.get(row.job_id, ""),
                "job_id": row.job_id,
                "platform": str(payload.get("platform") or ""),
                "url": str(payload.get("url") or ""),
            })
    items.sort(key=lambda i: str(i.get("at") or ""), reverse=True)
    return items[:_TIMELINE_LIMIT]


def loop_detail(session: Any, user_id: str, batch_id: str) -> dict:
    """Everything the project page needs: config, ranked variants, why, lineage, timeline."""
    from app.models.db.repositories import JobRepository

    anchor = find_anchor(session, batch_id, user_id)
    if anchor is None:
        raise LoopNotFound(batch_id)
    state = read_state(anchor)
    jobs = JobRepository(session).list_by_batch(batch_id, user_id)
    root_id = str(state.get("root_batch_id") or batch_id)
    root_anchor = anchor if root_id == batch_id else find_anchor(session, root_id, user_id)
    root_state = read_state(root_anchor) if root_anchor is not None else state

    lineage: list[dict] = []
    anchor_ids: dict[str, str] = {}
    for lineage_batch in [root_id, *list(root_state.get("children") or [])]:
        lineage_anchor = anchor if lineage_batch == batch_id else find_anchor(session, lineage_batch, user_id)
        if lineage_anchor is None:
            continue
        lineage_state = read_state(lineage_anchor)
        anchor_ids[lineage_anchor.id] = lineage_batch
        lineage.append({
            "batch_id": lineage_batch,
            "generation": int(lineage_state.get("generation", 1) or 1),
            "status": lineage_state.get("status", ""),
            "winner_job_id": lineage_state.get("winner_job_id", ""),
            "current": lineage_batch == batch_id,
        })
    anchor_ids.setdefault(anchor.id, batch_id)

    measured = {v.get("job_id"): v for v in state.get("variants") or [] if isinstance(v, dict)}
    ranked = {r.get("job_id"): r for r in (state.get("ranking") or {}).get("ranked", []) if isinstance(r, dict)}
    from .remake import winning_hook

    variants = []
    for job in jobs:
        m = measured.get(job.id, {})
        r = ranked.get(job.id, {})
        variants.append({
            "job_id": job.id,
            "title": _title(job),
            "hook": m.get("hook") or winning_hook(job)[0],
            "state": _STATE_LABELS.get(job.state, str(job.state)),
            "rank": r.get("rank"),
            "score": r.get("score"),
            "source": m.get("source", "none"),
            "views": m.get("views"),
            "likes": m.get("likes"),
            "comments": m.get("comments"),
            "shares": m.get("shares"),
            "saves": m.get("saves"),
            "engagement_rate": m.get("engagement_rate"),
            "avg_watch_frac": m.get("avg_watch_frac"),
            "completion_rate": m.get("completion_rate"),
            "rewatch_rate": m.get("rewatch_rate"),
            "posted_at": m.get("posted_at"),
            "posts": m.get("posts", []),
            "is_winner": job.id == state.get("winner_job_id"),
        })
    variants.sort(key=lambda v: (v["rank"] is None, v["rank"] or 0))

    job_cost, remake_cost = _costs()
    configured = bool(state)
    return {
        "batch_id": batch_id,
        "title": _title(anchor),
        "configured": configured,
        "mode": state.get("mode", "off"),
        "platforms": list(state.get("platforms") or []),
        "spend_cap_credits": int(root_state.get("spend_cap_credits", state.get("spend_cap_credits", 0)) or 0),
        "spent_credits": int(root_state.get("spent_credits", 0) or 0),
        "check_after_hours": state.get("check_after_hours"),
        "min_views": state.get("min_views"),
        "status": state.get("status", "not_configured" if not configured else ""),
        "note": state.get("note", ""),
        "generation": int(state.get("generation", 1) or 1),
        "root_batch_id": root_id,
        "parent_batch_id": state.get("parent_batch_id", ""),
        "check_due_at": state.get("check_due_at"),
        "last_post_at": state.get("last_post_at"),
        "last_checked_at": state.get("last_checked_at"),
        "checks": int(state.get("checks", 0) or 0),
        "early_read": bool(state.get("early_read")),
        "winner_job_id": state.get("winner_job_id", ""),
        "conclusive": bool(state.get("conclusive")),
        "ranking_reason": (state.get("ranking") or {}).get("reason", ""),
        "uses_retention": bool((state.get("ranking") or {}).get("uses_retention")),
        "explanation": state.get("explanation"),
        "remake_batch_id": state.get("remake_batch_id", ""),
        "remake_hooks": list(state.get("remake_hooks") or []),
        "variants": variants,
        "lineage": lineage,
        "timeline": _timeline(session, anchor_ids, {j.id: batch_id for j in jobs}),
        "publishing_enabled": _publishing_open(),
        "job_cost_credits": job_cost,
        "remake_cost_credits": remake_cost,
    }


__all__ = ["loop_board", "loop_detail"]
