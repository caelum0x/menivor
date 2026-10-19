"""Workflow canvas HTTP surface (owner-scoped).

    GET    /workflows                      my workflows + node types + a starter graph
    POST   /workflows                      create (starter chain when no graph)
    GET    /workflows/{id}                 one workflow + recent runs
    PUT    /workflows/{id}                 save name / graph (validated)
    DELETE /workflows/{id}
    POST   /workflows/{id}/run             run now (spend steps become pending approvals)
    PUT    /workflows/{id}/schedule        weekly / daily schedule (UTC), run by the beat tick
    POST   /workflows/runs/{run_id}/advance  move a run on after its approvals
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session
from app.domains._http import Call
from app.domains.brand_agent.gate import GateError
from app.domains.brand_agent.spaces import SpaceError
from app.domains.workflows import graph as graphs
from app.domains.workflows import models as _models  # noqa: F401  (registers tables)
from app.domains.workflows import service
from app.utils import utils

router = new_router()
_ERRORS = (service.WorkflowError, GateError, SpaceError, graphs.GraphError)


def _id():
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")


class WorkflowBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="", max_length=200)
    graph: Optional[dict[str, Any]] = None
    space_id: Optional[str] = Field(default=None, max_length=32)


class ScheduleBody(BaseModel):
    enabled: bool = True
    weekday: Optional[int] = Field(default=0, ge=0, le=6)
    hour: int = Field(default=9, ge=0, le=23)


def _call(request: Request, key: str = "", limit: int = 600) -> Call:
    return Call(request, _ERRORS, f"workflows:{key}" if key else "", get_session, limit=limit)


@router.get("/workflows", summary="My workflows, the step types and a starter chain")
def list_workflows(request: Request):
    with _call(request) as (session, user_id):
        return utils.get_response(200, {"workflows": service.list_workflows(session, user_id),
                                        "node_types": [{"type": k, **v} for k, v in graphs.NODE_TYPES.items()],
                                        "starter": graphs.starter()})


@router.post("/workflows", summary="Create a workflow")
def create_workflow(request: Request, body: WorkflowBody):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, {"workflow": service.create(session, user_id, name=body.name, graph=body.graph,
                                                                   space_id=body.space_id)})


@router.get("/workflows/{workflow_id}", summary="One workflow and its recent runs")
def get_workflow(request: Request, workflow_id: str = _id()):
    with _call(request) as (session, user_id):
        return utils.get_response(200, {"workflow": service.get(session, user_id, workflow_id),
                                        "runs": service.list_runs(session, user_id, workflow_id)})


@router.put("/workflows/{workflow_id}", summary="Save a workflow (the graph is checked)")
def save_workflow(request: Request, body: WorkflowBody, workflow_id: str = _id()):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, {"workflow": service.save(session, user_id, workflow_id,
                                                                 name=body.name or None, graph=body.graph)})


@router.delete("/workflows/{workflow_id}", summary="Delete a workflow")
def delete_workflow(request: Request, workflow_id: str = _id()):
    with _call(request, "write") as (session, user_id):
        service.delete(session, user_id, workflow_id)
        return utils.get_response(200, {"deleted": workflow_id})


@router.post("/workflows/{workflow_id}/run", summary="Run now: free steps run, spend steps wait for approval")
def run_workflow(request: Request, workflow_id: str = _id()):
    with _call(request, "run", limit=120) as (session, user_id):
        return utils.get_response(200, {"run": service.run(session, user_id, workflow_id)})


@router.put("/workflows/{workflow_id}/schedule", summary="Run on a schedule (UTC), always behind approvals")
def schedule_workflow(request: Request, body: ScheduleBody, workflow_id: str = _id()):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, {"workflow": service.set_schedule(
            session, user_id, workflow_id, enabled=body.enabled, weekday=body.weekday, hour=body.hour)})


@router.post("/workflows/runs/{run_id}/advance", summary="Move a run on after its approvals")
def advance_run(request: Request, run_id: str = _id()):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, {"run": service.advance(session, user_id, run_id)})


__all__ = ["router"]
