"""Saved workflows and their runs.

A run walks the graph in order. Free steps run now (brief from the Brain, script by
the Agent writer, captions as a render option). Spending steps (images, video) only
create pending Brand Agent actions. ``approve`` is the human gate: ``publish`` is
proposed (also pending) only after every spend action of the run was approved and
made something (:func:`advance`). Schedules use the same weekday/hour rule as Agent
routines and are run by the Celery beat tick; a scheduled run never spends either.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select, update

from app.domains.adstudio.extract import clean_text
from app.domains.brand_agent import gate, memory, routines, spaces, writers
from app.domains.brand_agent.models import AgentAction, AgentLibraryItem
from app.domains.workflows import graph as graphs
from app.domains.workflows.models import AgentWorkflow, WorkflowRun

MAX_WORKFLOWS = 30
UTC = timezone.utc
RUN_RUNNING, RUN_WAITING, RUN_PUBLISH, RUN_DONE, RUN_FAILED = (
    "running", "waiting_for_approval", "publish_pending", "done", "failed")


class WorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def view(row: AgentWorkflow) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "space_id": row.space_id, "graph": dict(row.graph or {}),
            "schedule": {"enabled": bool(row.schedule_enabled), "weekday": row.weekday, "hour": row.hour,
                         "label": routines.describe({"count": 1, "skill": "workflow_run", "weekday": row.weekday,
                                                     "hour": row.hour}).replace("1 x workflow run ", "Runs "),
                         "next_run_at": _iso(row.next_run_at), "last_run_at": _iso(row.last_run_at)},
            "updated_at": _iso(row.updated_at)}


def run_view(row: WorkflowRun) -> dict[str, Any]:
    return {"id": row.id, "workflow_id": row.workflow_id, "trigger": row.trigger, "status": row.status,
            "steps": list(row.steps or []), "error": row.error, "created_at": _iso(row.created_at)}


def _get(session: Any, user_id: str, workflow_id: str) -> AgentWorkflow:
    row = session.get(AgentWorkflow, workflow_id) if workflow_id else None
    if row is None or row.user_id != user_id:
        raise WorkflowError("workflow not found", 404)
    return row


def _graph(raw: Any) -> dict[str, Any]:
    try:
        return graphs.normalize(raw)
    except graphs.GraphError as exc:
        raise WorkflowError(exc.message, 422) from exc


def list_workflows(session: Any, user_id: str) -> list[dict[str, Any]]:
    rows = session.execute(select(AgentWorkflow).where(AgentWorkflow.user_id == user_id)
                           .order_by(AgentWorkflow.updated_at.desc())).scalars().all()
    return [view(r) for r in rows]


def create(session: Any, user_id: str, *, name: str, graph: Any = None, space_id: str | None = None) -> dict:
    if len(list_workflows(session, user_id)) >= MAX_WORKFLOWS:
        raise WorkflowError(f"You can keep up to {MAX_WORKFLOWS} workflows.")
    space = spaces.resolve(session, user_id, space_id)
    row = AgentWorkflow(user_id=user_id, space_id=space.id, name=clean_text(name, 200) or "Untitled workflow",
                        graph=_graph(graph) if graph else graphs.starter())
    session.add(row)
    session.flush()
    return view(row)


def get(session: Any, user_id: str, workflow_id: str) -> dict[str, Any]:
    return view(_get(session, user_id, workflow_id))


def save(session: Any, user_id: str, workflow_id: str, *, name: str | None = None, graph: Any = None) -> dict:
    row = _get(session, user_id, workflow_id)
    if name is not None:
        row.name = clean_text(name, 200) or row.name
    if graph is not None:
        row.graph = _graph(graph)
    row.updated_at = datetime.now(UTC)
    session.flush()
    return view(row)


def delete(session: Any, user_id: str, workflow_id: str) -> None:
    session.delete(_get(session, user_id, workflow_id))
    session.flush()


def set_schedule(session: Any, user_id: str, workflow_id: str, *, enabled: bool, weekday: int | None, hour: int,
                 now: datetime | None = None) -> dict:
    row = _get(session, user_id, workflow_id)
    try:
        routines.validate(count=1, hour=hour, weekday=weekday, skill="ad_variations")
    except routines.RoutineError as exc:
        raise WorkflowError(exc.message, 422) from exc
    row.schedule_enabled, row.weekday, row.hour = bool(enabled), weekday, int(hour)
    row.next_run_at = routines.next_run(weekday=weekday, hour=int(hour), after=now or datetime.now(UTC)) \
        if enabled else None
    session.flush()
    return view(row)


# --------------------------------------------------------------------------- run
def _request(sections: dict[str, Any], brief: str) -> str:
    name = ((sections.get("positioning") or {}).get("name") or "").strip()
    return brief or (f"An ad for {name}" if name else "An ad for our product")


def _spend(session: Any, row: AgentWorkflow, run_id: str, kind: str, count: int, prompt: str, extra: dict) -> dict:
    payload = {"prompt": prompt, "workflow_id": row.id, "workflow_run_id": run_id, **extra}
    title = f"{row.name}: {count} {'video' if kind == 'video' else 'image'}{'s' if count > 1 else ''}"
    if count > 1:
        return gate.propose(session, row.user_id, row.space_id, None, kind=gate.KIND_ROUTINE_BATCH, title=title,
                            payload={**payload, "count": count, "media": kind, "skill": "ad_variations"})
    return gate.propose(session, row.user_id, row.space_id, None,
                        kind=gate.KIND_VIDEO if kind == "video" else gate.KIND_IMAGE, title=title, payload=payload)


def run(session: Any, user_id: str, workflow_id: str, *, trigger: str = "manual", llm: Any = None) -> dict:
    row = _get(session, user_id, workflow_id)
    ordered = graphs.order(_graph(row.graph))
    run_row = WorkflowRun(workflow_id=row.id, user_id=user_id, trigger=trigger, status=RUN_RUNNING, steps=[])
    session.add(run_row)
    session.flush()
    sections = memory.current(session, row.space_id)["sections"]
    brief, script_text, steps = "", "", []
    video_steps: list[dict] = []
    for node in ordered:
        kind, data = node["type"], node["data"]
        step: dict[str, Any] = {"node_id": node["id"], "type": kind, "label": graphs.NODE_TYPES[kind]["label"]}
        if kind == "brief":
            brief = _request(sections, data.get("request", ""))
            step.update(status="done", output=brief)
        elif kind == "script":
            written = writers.script(sections, seconds=int(data.get("seconds", 30)), llm=llm)
            script_text = " ".join(str(line.get("text", line)) if isinstance(line, dict) else str(line)
                                   for line in written.get("lines") or [])
            step.update(status="done", output=script_text[:2000])
        elif kind in ("images", "video"):
            prompt = f"{brief}. {script_text}"[:3000] if script_text else brief
            action = _spend(session, row, run_row.id, "video" if kind == "video" else "image",
                            int(data.get("count", 1)), prompt, {"options": {}})
            step.update(status="pending_approval", action_id=action["id"], credits=action["credits_estimate"])
            if kind == "video":
                video_steps.append(step)
        elif kind == "captions":
            for vs in video_steps:
                action = session.get(AgentAction, vs["action_id"])
                action.payload = {**dict(action.payload or {}),
                                  "options": {**dict((action.payload or {}).get("options") or {}),
                                              "captions": data.get("style", "clean")}}
            step.update(status="done", output=f"{data.get('style', 'clean')} captions on the video")
        elif kind == "approve":
            step.update(status="waiting", output="Approve the steps above in the Agent queue.")
        elif kind == "publish":
            step.update(status="after_approval", platforms=data.get("platforms", ["tiktok"]))
        steps.append(step)
    spends = [s for s in steps if s.get("action_id")]
    run_row.steps = steps
    run_row.status = RUN_WAITING if spends else RUN_DONE
    session.flush()
    return run_view(run_row)


def advance(session: Any, user_id: str, run_id: str) -> dict:
    """After approvals: propose the publish step once every spend action made something."""
    run_row = session.get(WorkflowRun, run_id) if run_id else None
    if run_row is None or run_row.user_id != user_id:
        raise WorkflowError("run not found", 404)
    if run_row.status != RUN_WAITING:
        return run_view(run_row)
    steps = [dict(s) for s in run_row.steps or []]
    ids = [s["action_id"] for s in steps if s.get("action_id")]
    actions = {a.id: a for a in session.execute(select(AgentAction).where(AgentAction.id.in_(ids))).scalars()}
    for s in steps:
        if s.get("action_id") in actions:
            s["status"] = {"executed": "done", "rejected": "rejected", "failed": "failed"}.get(
                actions[s["action_id"]].status, s["status"])
    if any(s["status"] in ("rejected", "failed") for s in steps if s.get("action_id")):
        run_row.status, run_row.error = RUN_FAILED, "A step was rejected or failed; nothing was published."
    elif all(s["status"] == "done" for s in steps if s.get("action_id")):
        for s in steps:
            if s["type"] == "approve":
                s["status"] = "done"
        publish = next((s for s in steps if s["type"] == "publish"), None)
        if publish is None:
            run_row.status = RUN_DONE
        else:
            wf = session.get(AgentWorkflow, run_row.workflow_id)
            video = session.execute(select(AgentLibraryItem).where(
                AgentLibraryItem.action_id.in_(ids), AgentLibraryItem.kind == "video")).scalars().first()
            action = gate.propose(session, user_id, wf.space_id, None, kind=gate.KIND_PUBLISH,
                                  title=f"{wf.name}: publish", payload={
                                      "job_id": video.ref if video is not None else "",
                                      "platforms": publish.get("platforms") or ["tiktok"],
                                      "workflow_run_id": run_row.id})
            publish.update(status="pending_approval", action_id=action["id"])
            run_row.status = RUN_PUBLISH
    run_row.steps = steps
    session.flush()
    return run_view(run_row)


def list_runs(session: Any, user_id: str, workflow_id: str, limit: int = 20) -> list[dict]:
    _get(session, user_id, workflow_id)
    rows = session.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id)
                           .order_by(WorkflowRun.created_at.desc()).limit(limit)).scalars().all()
    return [run_view(r) for r in rows]


def run_due(session: Any, *, now: datetime | None = None, limit: int = 100) -> int:
    """Beat: start due scheduled workflows (pending actions only) and advance waiting runs."""
    moment = now or datetime.now(UTC)
    due = session.execute(select(AgentWorkflow).where(AgentWorkflow.schedule_enabled.is_(True),
                                                      AgentWorkflow.next_run_at <= moment)
                          .order_by(AgentWorkflow.next_run_at).limit(limit)).scalars().all()
    started = 0
    for row in due:
        scheduled = row.next_run_at
        following = routines.next_run(weekday=row.weekday, hour=row.hour, after=moment)
        claimed = session.execute(update(AgentWorkflow).where(AgentWorkflow.id == row.id,
                                                              AgentWorkflow.next_run_at == scheduled)
                                  .values(next_run_at=following, last_run_at=moment)
                                  .execution_options(synchronize_session=False)).rowcount
        if not claimed:
            continue
        try:
            run(session, row.user_id, row.id, trigger="schedule")
            started += 1
        except Exception as exc:  # noqa: BLE001 - one broken workflow never stops the tick
            logger.warning(f"workflow {row.id} scheduled run failed: {type(exc).__name__}")
    for waiting in session.execute(select(WorkflowRun).where(WorkflowRun.status == RUN_WAITING).limit(500)).scalars():
        try:
            advance(session, waiting.user_id, waiting.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"workflow run {waiting.id} advance failed: {type(exc).__name__}")
    session.flush()
    return started


__all__ = ["WorkflowError", "advance", "create", "delete", "get", "list_runs", "list_workflows", "run", "run_due",
           "save", "set_schedule", "view"]
