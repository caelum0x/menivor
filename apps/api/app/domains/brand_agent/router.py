"""Brand Agent HTTP surface (owner-scoped, rate limited). All routes under ``/api/v1/agent``.

    GET    /agent/overview                         sidebar: space, Brain badge, recents, counts, credits
    GET    /agent/spaces | POST /agent/spaces      brand spaces
    POST   /agent/sessions                         new session (default space when none given)
    GET    /agent/sessions                         recents
    GET    /agent/sessions/{id}                    one session with its messages
    POST   /agent/sessions/{id}/messages           send text -> assistant messages (JSON)
    POST   /agent/sessions/{id}/chips              Yes / No / Connect / Retry / Skip / Approve / Reject
    POST   /agent/sessions/{id}/stream             text or chip -> Server-Sent Events
    GET    /agent/spaces/{id}/memory               Brain (current sections + version)
    PUT    /agent/spaces/{id}/memory/{section}     edit a section (a new version)
    GET    /agent/spaces/{id}/memory/history       versions (optional ?section=)
    POST   /agent/spaces/{id}/memory/seen          clear the Brain badge
    GET    /agent/actions                          approval queue (optional ?status=)
    POST   /agent/actions/{id}/approve|reject      the approval gate
    GET|POST /agent/routines, PATCH|DELETE /agent/routines/{id}
    GET|POST /agent/inspirations, DELETE /agent/inspirations/{id}
    GET|POST /agent/skills, GET|POST /agent/folders, GET /agent/library, PATCH /agent/library/{id}
    GET    /agent/connectors                       honest connection state per connector
    GET    /agent/credits                          free-trial credits meter from the credit ledger
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Literal, Optional

from fastapi import Path, Query, Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.brand_agent import agent, gate, inspirations, library, memory, routines, sessions, setup_flow
from app.domains.brand_agent import skills, spaces
from app.domains.brand_agent import models as _models  # noqa: F401  (registers tables)
from app.domains.brand_agent.deps import AgentDeps, default_deps
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

_WINDOW_S = 3600
_MESSAGE_LIMIT = 240
_WRITE_LIMIT = 240
_DECIDE_LIMIT = 120
_STREAM_CHUNK = 24
_DOMAIN_ERRORS = (
    agent.AgentError, gate.GateError, inspirations.InspirationError, library.LibraryError, memory.MemoryError_,
    routines.RoutineError, sessions.SessionError, setup_flow.SetupError, skills.SkillError, spaces.SpaceError,
)


def build_deps(request: Request | None = None) -> AgentDeps:
    return default_deps()


def _id() -> Any:
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")


def _error(request_id: str, status_code: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status_code, message=f"{request_id}: {message}")


class _Call:
    """Auth + DB session + domain-error mapping for one request."""

    def __init__(self, request: Request, limit_key: str | None = None, limit: int = _WRITE_LIMIT) -> None:
        self.request = request
        self.request_id = base.get_task_id(request)
        self.limit_key = limit_key
        self.limit = limit
        self._cm: Any = None

    def __enter__(self) -> tuple[Any, str]:
        require_database(self.request_id)
        self._cm = get_session()
        session = self._cm.__enter__()
        try:
            user_id = str(resolve_principal(self.request, session, self.request_id).id)
            if self.limit_key:
                enforce_rate_limit(self.request, f"agent:{self.limit_key}:{user_id}", limit=self.limit,
                                   window_s=_WINDOW_S)
        except BaseException as exc:
            self._cm.__exit__(type(exc), exc, exc.__traceback__)
            raise
        return session, user_id

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            handled = self._cm.__exit__(exc_type, exc, tb)
        except _DOMAIN_ERRORS as err:  # rolled back by the session scope, then mapped
            raise _error(self.request_id, err.status_code, err.message) from err
        if isinstance(exc, _DOMAIN_ERRORS):
            raise _error(self.request_id, exc.status_code, exc.message) from exc
        return bool(handled)


def _ok(data: Any) -> dict[str, Any]:
    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# Overview, spaces, credits, connectors
# --------------------------------------------------------------------------- #
def _credits(session: Any, user_id: str) -> dict[str, Any]:
    from sqlalchemy import func, select

    from app.models.db.models import CreditLedger
    from app.models.db.repositories import CreditRepository
    from app.services.billing.plans import SIGNUP_GRANT

    used = session.execute(
        select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
            CreditLedger.user_id == user_id, CreditLedger.workspace_id.is_(None), CreditLedger.delta < 0)
    ).scalar()
    return {"balance": CreditRepository(session).balance(user_id), "trial_grant": int(SIGNUP_GRANT),
            "used": -int(used or 0)}


@router.get("/agent/overview", summary="Agent sidebar: space, Brain badge, recents, counts, credits")
def overview(request: Request, space_id: Optional[str] = Query(default=None, max_length=32)):
    with _Call(request) as (session, user_id):
        space = spaces.resolve(session, user_id, space_id)
        brain = memory.current(session, space.id)
        recents = sessions.recents(session, user_id, space_id=space.id)
        counts = {
            "pending_actions": len(gate.list_actions(session, user_id, status=gate.STATUS_PENDING,
                                                     space_id=space.id)),
            "routines": len(routines.list_routines(session, user_id, space.id)),
            "inspirations": len(inspirations.list_items(session, user_id, space.id)),
            "library": len(library.list_items(session, user_id, space.id)),
        }
        return _ok({
            "space": spaces.view(space),
            "spaces": [spaces.view(s) for s in spaces.list_spaces(session, user_id)],
            "brain": {"version": brain["version"], "unseen": memory.unseen_count(session, space.id),
                      "sections": sorted(brain["sections"])},
            "recents": [sessions.view(r) for r in recents],
            "counts": counts,
            "folders": library.list_folders(session, user_id, space.id),
            "credits": _credits(session, user_id),
        })


class SpaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=200)
    website_url: str = Field(default="", max_length=2048)


@router.get("/agent/spaces", summary="List brand spaces")
def list_spaces(request: Request):
    with _Call(request) as (session, user_id):
        spaces.ensure_default(session, user_id)
        return _ok({"spaces": [spaces.view(s) for s in spaces.list_spaces(session, user_id)]})


@router.post("/agent/spaces", summary="Create a brand space")
def create_space(request: Request, body: SpaceBody):
    with _Call(request, "space") as (session, user_id):
        return _ok({"space": spaces.view(spaces.create(session, user_id, name=body.name,
                                                       website_url=body.website_url))})


@router.get("/agent/credits", summary="Free-trial credits meter")
def credits(request: Request):
    with _Call(request) as (session, user_id):
        return _ok(_credits(session, user_id))


def _connectors(session: Any, user_id: str, deps: AgentDeps) -> list[dict[str, Any]]:
    from app.domains.brand_agent.ports.ad_clone import StubAdClone
    from app.domains.brand_agent.ports.integrations import NOT_CONNECTED, StubIntegrations

    out: list[dict[str, Any]] = []
    try:
        accounts = deps.integrations.list_connected_accounts(user_id)
    except Exception as exc:  # noqa: BLE001 - shown as "not connected"
        logger.warning(f"brand agent connectors: accounts lookup failed: {type(exc).__name__}")
        accounts = []
    meta = [a for a in accounts if str(a.get("platform", "")).lower() == "meta"]
    if meta:
        out.append({"id": "meta_ads", "name": "Meta Ads", "status": "connected", "detail": meta[0].get("name", "")})
    elif isinstance(deps.integrations, StubIntegrations):
        out.append({"id": "meta_ads", "name": "Meta Ads", "status": "unavailable", "detail": NOT_CONNECTED})
    else:
        out.append({"id": "meta_ads", "name": "Meta Ads", "status": "not_connected",
                    "detail": "Connect in Settings > Integrations"})
    tiktok = 0
    try:
        from sqlalchemy import func, select

        from app.domains.multipost.models import MultipostAccount

        tiktok = int(session.execute(select(func.count()).select_from(MultipostAccount).where(
            MultipostAccount.user_id == user_id, MultipostAccount.provider == "tiktok")).scalar() or 0)
    except Exception:  # noqa: BLE001 - optional table
        tiktok = 0
    out.append({"id": "tiktok", "name": "TikTok", "status": "connected" if tiktok else "not_connected",
                "detail": f"{tiktok} account(s)" if tiktok else "Connect in Autopost"})
    search_on = bool(getattr(deps.search, "enabled", False))
    out.append({"id": "web_search", "name": "Web search", "status": "connected" if search_on else "off",
                "detail": "" if search_on else "Set SEARXNG_URL on the server"})
    clone_installed = not isinstance(deps.ad_clone, StubAdClone)
    clone_ready = clone_installed and bool(getattr(deps.ad_clone, "enabled", True))
    clone_detail = "" if clone_ready else ("Switched off on this server" if clone_installed
                                           else "Not installed on this server yet")
    out.append({"id": "ad_clone", "name": "Ad Clone", "status": "connected" if clone_ready else "unavailable",
                "detail": clone_detail})
    out.append({"id": "writer", "name": "AI writer", "status": "connected" if deps.llm is not None else "off",
                "detail": "Claude through Relay" if deps.llm is not None else "Templates from your brand memory"})
    return out


@router.get("/agent/connectors", summary="Connector status")
def connectors(request: Request):
    deps = build_deps(request)
    with _Call(request) as (session, user_id):
        return _ok({"connectors": _connectors(session, user_id, deps)})


# --------------------------------------------------------------------------- #
# Sessions, messages, chips, stream
# --------------------------------------------------------------------------- #
class SessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    space_id: Optional[str] = Field(default=None, max_length=32)
    title: str = Field(default="", max_length=200)


class MessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1, max_length=4000)


class ChipBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice: Literal["yes", "no", "connect", "retry", "skip", "approve", "reject", "use_product", "recheck"]
    step: str = Field(default="", max_length=32)
    action_id: Optional[str] = Field(default=None, max_length=32)
    value: Optional[str] = Field(default=None, max_length=64)
    edits: Optional[dict[str, Any]] = None


class StreamBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Optional[str] = Field(default=None, max_length=4000)
    choice: Optional[Literal["yes", "no", "connect", "retry", "skip", "approve", "reject", "use_product",
                             "recheck"]] = None
    step: str = Field(default="", max_length=32)
    action_id: Optional[str] = Field(default=None, max_length=32)
    value: Optional[str] = Field(default=None, max_length=64)
    edits: Optional[dict[str, Any]] = None


@router.post("/agent/sessions", summary="Start an agent session")
def create_session(request: Request, body: SessionBody):
    with _Call(request, "session") as (session, user_id):
        space = spaces.resolve(session, user_id, body.space_id)
        row = sessions.create(session, user_id, space.id, title=body.title)
        return _ok({"session": sessions.view(row)})


@router.get("/agent/sessions", summary="Recent agent sessions")
def list_sessions(request: Request, space_id: Optional[str] = Query(default=None, max_length=32)):
    with _Call(request) as (session, user_id):
        return _ok({"sessions": [sessions.view(r) for r in sessions.recents(session, user_id, space_id=space_id)]})


@router.get("/agent/sessions/{session_id}", summary="One session with its messages")
def get_session_messages(request: Request, session_id: str = _id()):
    with _Call(request) as (session, user_id):
        row = sessions.get(session, user_id, session_id)
        return _ok({"session": sessions.view(row), "setup": _setup_view(row),
                    "messages": sessions.messages(session, user_id, session_id)})


def _setup_view(row: Any) -> dict[str, Any]:
    state = setup_flow.state_of(row)
    return {"step": state.get("step"), "awaiting_edit": state.get("awaiting_edit")}


def _run(session: Any, deps: AgentDeps, user_id: str, session_id: str, *, text: str | None = None,
         choice: str | None = None, step: str = "", action_id: str | None = None,
         edits: dict[str, Any] | None = None, value: str | None = None) -> list[dict[str, Any]]:
    if text:
        return agent.handle_text(session, deps, user_id, session_id, text)
    return agent.handle_chip(session, deps, user_id, session_id, step=step, choice=str(choice), edits=edits,
                             action_id=action_id, value=value)


@router.post("/agent/sessions/{session_id}/messages", summary="Send a message to the agent")
def post_message(request: Request, body: MessageBody, session_id: str = _id()):
    deps = build_deps(request)
    with _Call(request, "message", _MESSAGE_LIMIT) as (session, user_id):
        return _ok({"messages": _run(session, deps, user_id, session_id, text=body.text)})


@router.post("/agent/sessions/{session_id}/chips", summary="Answer a Yes/No/Approve chip")
def post_chip(request: Request, body: ChipBody, session_id: str = _id()):
    deps = build_deps(request)
    with _Call(request, "message", _MESSAGE_LIMIT) as (session, user_id):
        return _ok({"messages": _run(session, deps, user_id, session_id, choice=body.choice, step=body.step,
                                     action_id=body.action_id, edits=body.edits, value=body.value)})


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _stream_events(session_id: str, messages: list[dict[str, Any]]) -> Iterator[str]:
    yield _sse("start", {"session_id": session_id})
    for message in messages:
        content = message.get("content", "")
        for i in range(0, len(content), _STREAM_CHUNK):
            yield _sse("delta", {"message_id": message["id"], "text": content[i:i + _STREAM_CHUNK]})
        yield _sse("message", message)
    yield _sse("done", {"count": len(messages)})


@router.post("/agent/sessions/{session_id}/stream", summary="Send text or a chip; stream the reply (SSE)")
def stream(request: Request, body: StreamBody, session_id: str = _id()):
    request_id = base.get_task_id(request)
    if not (body.text or "").strip() and not body.choice:
        raise _error(request_id, 422, "send text or a chip choice")
    deps = build_deps(request)
    with _Call(request, "message", _MESSAGE_LIMIT) as (session, user_id):
        messages = _run(session, deps, user_id, session_id, text=(body.text or "").strip() or None,
                        choice=body.choice, step=body.step, action_id=body.action_id, edits=body.edits,
                        value=body.value)
    return StreamingResponse(_stream_events(session_id, messages), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
# Brain (brand memory)
# --------------------------------------------------------------------------- #
class MemoryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: dict[str, Any]


@router.get("/agent/spaces/{space_id}/memory", summary="Brand memory (Brain)")
def get_memory(request: Request, space_id: str = _id()):
    with _Call(request) as (session, user_id):
        spaces.get(session, user_id, space_id)
        return _ok({**memory.current(session, space_id), "unseen": memory.unseen_count(session, space_id)})


@router.put("/agent/spaces/{space_id}/memory/{section}", summary="Edit one brand memory section")
def put_memory(request: Request, body: MemoryBody, space_id: str = _id(),
               section: str = Path(..., max_length=32)):
    with _Call(request, "memory") as (session, user_id):
        spaces.get(session, user_id, space_id)
        return _ok(memory.write(session, user_id, space_id, section, body.data, source=memory.SOURCE_USER))


@router.get("/agent/spaces/{space_id}/memory/history", summary="Brand memory versions")
def memory_history(request: Request, space_id: str = _id(),
                   section: Optional[str] = Query(default=None, max_length=32)):
    with _Call(request) as (session, user_id):
        spaces.get(session, user_id, space_id)
        return _ok({"versions": memory.history(session, space_id, section=section)})


@router.post("/agent/spaces/{space_id}/memory/seen", summary="Mark brand memory updates as seen")
def memory_seen(request: Request, space_id: str = _id()):
    with _Call(request) as (session, user_id):
        return _ok({"seen_version": memory.mark_seen(session, user_id, space_id)})


# --------------------------------------------------------------------------- #
# Approval gate
# --------------------------------------------------------------------------- #
@router.get("/agent/actions", summary="Agent actions (approval queue)")
def list_actions(request: Request, status: Optional[str] = Query(default=None, max_length=16),
                 space_id: Optional[str] = Query(default=None, max_length=32)):
    with _Call(request) as (session, user_id):
        return _ok({"actions": gate.list_actions(session, user_id, status=status, space_id=space_id)})


def _decide(request: Request, action_id: str, decision: str) -> dict[str, Any]:
    deps = build_deps(request)
    with _Call(request, "decide", _DECIDE_LIMIT) as (session, user_id):
        return _ok({"action": gate.decide(session, deps, user_id, action_id, decision)})


@router.post("/agent/actions/{action_id}/approve", summary="Approve an agent action (spends or publishes)")
def approve_action(request: Request, action_id: str = _id()):
    return _decide(request, action_id, gate.APPROVE)


@router.post("/agent/actions/{action_id}/reject", summary="Reject an agent action")
def reject_action(request: Request, action_id: str = _id()):
    return _decide(request, action_id, gate.REJECT)


# --------------------------------------------------------------------------- #
# Routines, inspirations, skills, folders, library
# --------------------------------------------------------------------------- #
class RoutineBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    space_id: Optional[str] = Field(default=None, max_length=32)
    text: Optional[str] = Field(default=None, max_length=300)
    name: str = Field(default="", max_length=200)
    skill: Optional[str] = Field(default=None, max_length=64)
    count: Optional[int] = Field(default=None, ge=1, le=routines.MAX_COUNT)
    weekday: Optional[int] = Field(default=None, ge=0, le=6)
    hour: Optional[int] = Field(default=None, ge=0, le=23)


class RoutinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Optional[bool] = None
    count: Optional[int] = Field(default=None, ge=1, le=routines.MAX_COUNT)
    hour: Optional[int] = Field(default=None, ge=0, le=23)


@router.get("/agent/routines", summary="Routines")
def list_routines(request: Request, space_id: Optional[str] = Query(default=None, max_length=32)):
    with _Call(request) as (session, user_id):
        return _ok({"routines": routines.list_routines(session, user_id, space_id)})


@router.post("/agent/routines", summary="Create a routine (runs need approval)")
def create_routine(request: Request, body: RoutineBody):
    with _Call(request, "routine") as (session, user_id):
        space = spaces.resolve(session, user_id, body.space_id)
        if body.text:
            rule = routines.parse_schedule(body.text)
            if rule is None:
                raise routines.RoutineError("Say how often, for example \"3 new ad variations every Monday\".")
            name = body.name or body.text
        else:
            rule = {"skill": body.skill or "ad_variations", "count": body.count or 1, "weekday": body.weekday,
                    "hour": routines.DEFAULT_HOUR if body.hour is None else body.hour}
            name = body.name
        return _ok({"routine": routines.create(session, user_id, space.id, name=name, skill=rule["skill"],
                                               count=rule["count"], weekday=rule["weekday"], hour=rule["hour"])})


@router.patch("/agent/routines/{routine_id}", summary="Pause, resume or change a routine")
def patch_routine(request: Request, body: RoutinePatch, routine_id: str = _id()):
    with _Call(request, "routine") as (session, user_id):
        return _ok({"routine": routines.update(session, user_id, routine_id, enabled=body.enabled,
                                               count=body.count, hour=body.hour)})


@router.delete("/agent/routines/{routine_id}", summary="Delete a routine")
def delete_routine(request: Request, routine_id: str = _id()):
    with _Call(request, "routine") as (session, user_id):
        routines.delete(session, user_id, routine_id)
        return _ok({"deleted": True})


class InspirationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(..., min_length=1, max_length=2048)
    title: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=2000)
    space_id: Optional[str] = Field(default=None, max_length=32)


@router.get("/agent/inspirations", summary="Inspirations")
def list_inspirations(request: Request, space_id: Optional[str] = Query(default=None, max_length=32)):
    with _Call(request) as (session, user_id):
        return _ok({"inspirations": inspirations.list_items(session, user_id, space_id)})


@router.post("/agent/inspirations", summary="Save an inspiration link")
def add_inspiration(request: Request, body: InspirationBody):
    with _Call(request, "inspiration") as (session, user_id):
        space = spaces.resolve(session, user_id, body.space_id)
        return _ok({"inspiration": inspirations.add(session, user_id, space.id, body.url, title=body.title,
                                                    notes=body.notes)})


@router.delete("/agent/inspirations/{item_id}", summary="Remove an inspiration")
def delete_inspiration(request: Request, item_id: str = _id()):
    with _Call(request, "inspiration") as (session, user_id):
        inspirations.delete(session, user_id, item_id)
        return _ok({"deleted": True})


class SkillBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=120)
    instructions: str = Field(..., min_length=1, max_length=4000)


@router.get("/agent/skills", summary="Built-in and custom skills")
def list_skills(request: Request):
    with _Call(request) as (session, user_id):
        return _ok({"skills": skills.list_skills(session, user_id)})


@router.post("/agent/skills", summary="Create a custom skill")
def create_skill(request: Request, body: SkillBody):
    with _Call(request, "skill") as (session, user_id):
        return _ok({"skill": skills.create(session, user_id, name=body.name, instructions=body.instructions)})


class FolderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=120)
    space_id: Optional[str] = Field(default=None, max_length=32)


class LibraryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_id: Optional[str] = Field(default=None, max_length=32)


@router.get("/agent/folders", summary="Folders")
def list_folders(request: Request, space_id: Optional[str] = Query(default=None, max_length=32)):
    with _Call(request) as (session, user_id):
        return _ok({"folders": library.list_folders(session, user_id, space_id)})


@router.post("/agent/folders", summary="Create a folder")
def create_folder(request: Request, body: FolderBody):
    with _Call(request, "folder") as (session, user_id):
        space = spaces.resolve(session, user_id, body.space_id)
        return _ok({"folder": library.create_folder(session, user_id, space.id, body.name)})


@router.get("/agent/library", summary="Generated assets")
def list_library(request: Request, space_id: Optional[str] = Query(default=None, max_length=32),
                 folder_id: Optional[str] = Query(default=None, max_length=32)):
    with _Call(request) as (session, user_id):
        return _ok({"items": library.list_items(session, user_id, space_id, folder_id=folder_id)})


@router.patch("/agent/library/{item_id}", summary="Move a library item into a folder")
def patch_library(request: Request, body: LibraryPatch, item_id: str = _id()):
    with _Call(request, "library") as (session, user_id):
        return _ok({"item": library.move(session, user_id, item_id, body.folder_id)})


__all__ = ["build_deps", "router"]
