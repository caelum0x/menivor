"""Approve-to-render: price check, cost cap, AI-video credit debit, the Library job and the film project.

``approve`` runs inside the caller's session (the router wraps it with the shared
Idempotency-Key reservation), so a retried click replays the same job instead of paying twice.
The worker (:mod:`render_tasks`) settles credits to what the engine actually cost.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from . import engines, service
from .adapters import EngineNotReady

JOB_KIND = "ad_clone"
DEBIT_REASON = "adclone"
STATE_COMPLETE, STATE_FAILED, STATE_PROCESSING = 1, -1, 4
WORKER_ENGINES = ("kling", "replicate", "higgsfield_kling", "minimax_hailuo", "runpod_wan")


def quote(plan: Mapping[str, Any], engine: str | None = None, env: Mapping[str, str] | None = None) -> dict:
    """The worst-case USD of the chosen engine and the AI-video credits it holds."""
    from app.services.billing.premium_credits import ai_video_credits_for_usd

    chosen = engines.choose(engines.estimates(plan, env), engine)
    return {"engine": chosen["engine"], "label": chosen["label"], "usd": chosen["usd"],
            "ai_video_credits": ai_video_credits_for_usd(chosen["usd"]), "configured": chosen["configured"],
            "price_basis": chosen.get("price_basis", "estimate")}


def approve(session: Any, user_id: str, *, plan: Mapping[str, Any], engine: str | None, quoted_credits: int,
            request_id: str = "", env: Mapping[str, str] | None = None) -> Any:
    """Create the paid render job (Library) + film project and hold its credits. Raises AdCloneError."""
    from app.models.db.film import FilmProject, FilmShot
    from app.models.db.repositories import JobRepository
    from app.services.billing import premium_credits as pc

    env = os.environ if env is None else env
    service.checked_plan(plan)
    if not service.paid_enabled(env):
        raise service.AdCloneError(403, f"paid rendering is off; set {service.PAID_ENV}=1 to allow approvals")
    q = quote(plan, engine, env)
    if not q["configured"]:
        raise service.AdCloneError(409, f"{q['label']} has no keys on this server")
    if q["engine"] not in WORKER_ENGINES:
        raise EngineNotReady(f"{q['label']}: no paid worker path for this engine")
    cap = service.cap_usd(env)
    if q["usd"] > cap:
        raise service.AdCloneError(409, f"worst case ${q['usd']:.2f} is above the cap ${cap:.2f}")
    if int(quoted_credits) != q["ai_video_credits"]:
        raise service.AdCloneError(409, "the price changed; check the new price first")
    title = f"Ad Clone {str((plan.get('clone') or {}).get('variation') or 'a').upper()}: {plan.get('slug', '')}"[:200]
    project = FilmProject(user_id=user_id, title=title, shot_count=len(plan.get("shots") or []), status="rendering",
                          total_runtime_s=int(plan.get("target_seconds") or 30))
    session.add(project)
    session.flush()
    params = {"_correlation_id": request_id, "plan": dict(plan), "engine": q["engine"], "quoted_usd": q["usd"],
              "cap_usd": cap, "ai_video_credits": q["ai_video_credits"],
              "project_id": project.id, "_stage": "queued", "_spent_usd": 0.0, "aspect": plan.get("aspect", "9:16")}
    job = JobRepository(session).create(user_id=user_id, kind=JOB_KIND, params=params)
    try:
        pc.debit(session, user_id, pc.KIND_AI_VIDEO, q["ai_video_credits"], f"{DEBIT_REASON}:{job.id}", job.id)
    except pc.InsufficientPremiumCredits as exc:
        raise service.AdCloneError(402, f"this render needs {exc.needed} AI-video credits; you have "
                                        f"{exc.available}") from exc
    for i, s in enumerate(plan.get("shots") or []):
        session.add(FilmShot(project_id=project.id, shot_key=str(s["id"]), order=i, role=str(s.get("kind", "")),
                             duration_ms=int(s.get("dur", 0)) * 1000, prompt=str(s.get("prompt", ""))[:4000],
                             render_job_id=job.id, status="pending"))
    job.state = STATE_PROCESSING
    session.flush()
    return job


def enqueue(job_id: str) -> str:
    from .render_tasks import run_adclone_render_task

    return str(run_adclone_render_task.apply_async(args=[job_id], queue="generation").id)


def view(job: Any) -> dict:
    from app.domains.gallery.service import media_url

    params = dict(job.params or {})
    shots = {sid: {"stage": s.get("stage"), "tries": s.get("tries", 0)} for sid, s in (params.get("_shots") or {}).items()}
    return {"job_id": job.id, "state": job.state, "stage": params.get("_stage", "queued"), "engine": params.get("engine"),
            "quoted_usd": params.get("quoted_usd"), "spent_usd": params.get("_spent_usd", 0.0),
            "ai_video_credits": params.get("ai_video_credits"), "project_id": params.get("project_id"),
            "aspect": params.get("aspect"), "shots": shots, "video_url": media_url(job.result_key or ""),
            "poster_url": media_url(job.poster_key or ""), "error": params.get("_error", "")}
