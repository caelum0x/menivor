"""Brand Agent chat orchestrator: one user message or chip -> stored assistant messages.

Intent routing is deterministic (testable, free); the LLM (Relay only) writes
text where it helps. Order: pending setup edit -> brand setup -> routine ->
inspiration -> ad clone -> hooks -> script -> audience change -> publish ->
image -> video -> free answer. Tools that spend credits or publish only create
a pending action in :mod:`gate` with Approve / Reject chips.
"""

from __future__ import annotations

import re
from typing import Any

from app.domains.brand_agent import copy_rules, gate, inspirations, library, memory, preflight, proposals, routines
from app.domains.brand_agent import sessions, setup_flow, spaces, writers
from app.domains.brand_agent.models import AgentMessage, AgentSession
from app.domains.brand_agent.ports.base import PortUnavailable

MAX_TEXT = 4000
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
_SETUP_RE = re.compile(r"\bset\s*-?\s*up\b.*\bbrand\b|\bbrand\b.*\bfrom\b.*\bwebsite\b", re.I)
_ROUTINE_RE = re.compile(r"\bevery\s+(?:day|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
                         r"\bdaily\b|\broutine\b", re.I)
_INSPIRATION_RE = re.compile(r"\binspiration", re.I)
_CLONE_RE = re.compile(r"\bclone\b|\bremake\b|\brecreate\b", re.I)
_HOOK_RE = re.compile(r"\bhooks?\b", re.I)
_SCRIPT_RE = re.compile(r"\bscripts?\b", re.I)
_AUDIENCE_RE = re.compile(r"\b(?:change|update|set|fix)\b.*\baudience\b|\baudience\s+(?:is|are|should)\b", re.I)
_PUBLISH_RE = re.compile(r"\b(?:publish|post it|post my|post to|schedule (?:a )?post)\b", re.I)
_IMAGE_RE = re.compile(r"\b(?:image|picture|static|banner|photo|poster)\b", re.I)
_VIDEO_RE = re.compile(r"\b(?:video|reel|clip|ugc)\b", re.I)
_SECONDS_RE = re.compile(r"\b(\d{1,2})\s*(?:s|sec|secs|second|seconds)\b", re.I)
_COUNT_RE = re.compile(r"\b(\d{1,2})\b")
_PLATFORMS = (("tiktok", "tiktok"), ("instagram", "instagram"), ("reels", "instagram"), ("youtube", "youtube_shorts"),
              ("shorts", "youtube_shorts"))
HELP_TEXT = ("I can set up your brand from your website, write scripts and hooks, make images and videos, clone an "
             "ad from a link, save inspirations, and schedule routines like \"3 new ad variations every Monday\". "
             "Anything that spends credits or publishes waits for your approval.")


def _approval_chips(action: dict[str, Any]) -> list[dict[str, str]]:
    return [{"label": "Approve", "choice": "approve", "action_id": action["id"]},
            {"label": "Reject", "choice": "reject", "action_id": action["id"]}]


def _views(session: Any, user_id: str, rows: list[AgentMessage]) -> list[dict[str, Any]]:
    actions = gate.views_by_id(session, user_id, [r.action_id for r in rows if r.action_id])
    return [sessions.message_view(r, actions.get(r.action_id or "")) for r in rows]


def _say(session: Any, row: AgentSession, text: str, **kw: Any) -> AgentMessage:
    return sessions.add_message(session, row, sessions.ROLE_ASSISTANT, text, **kw)


def _ready_message(session: Any, row: AgentSession, action: dict[str, Any], explain: str) -> AgentMessage:
    cost = action["credits_estimate"]
    cost_text = f" It uses about {cost} credit{'s' if cost != 1 else ''}." if cost else " It costs nothing."
    return _say(session, row, f"{explain}{cost_text} Approve to start, or Reject.", chips=_approval_chips(action),
                action_id=action["id"], card={"type": "action", "data": action})


def _blocked_message(session: Any, row: AgentSession, action: dict[str, Any], explain: str) -> AgentMessage:
    first = action["needs"][0]
    detail = f" {first['detail']}" if first.get("detail") else ""
    return _say(session, row, f"{explain} First: {first['title']}{detail}",
                chips=preflight.chips(action["id"], action["needs"]), action_id=action["id"],
                card={"type": "action", "data": action})


def _point_back(session: Any, row: AgentSession, blocked: Any) -> AgentMessage:
    needs = (blocked.result or {}).get("needs") or []
    what = needs[0]["title"] if needs else "the step above"
    return _say(session, row, f"That is still waiting on the step above: {what} Finish it there and I'll carry on.")


def _propose(session: Any, deps: Any, row: AgentSession, *, kind: str, title: str, payload: dict[str, Any],
             explain: str) -> AgentMessage:
    """Preflight first: Approve only when nothing is missing; otherwise one inline step that fixes it."""
    waiting = gate.open_blocked(session, row.user_id, row.id, kind)
    if waiting is not None:
        return _point_back(session, row, waiting)  # never show the same failing card twice
    needs = preflight.check(session, deps, row.user_id, row.space_id, kind, payload, _sections(session, row))
    payload = _with_preset(session, deps, row, kind, payload) if not needs else payload
    action = gate.propose(session, row.user_id, row.space_id, row.id, kind=kind, title=title, payload=payload,
                          needs=needs)
    if needs:
        return _blocked_message(session, row, action, explain)
    return _ready_message(session, row, action, explain)


def _with_preset(session: Any, deps: Any, row: AgentSession, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Pin the Ad Clone product preset the preflight found, so the approved run uses exactly it."""
    resolve = getattr(deps.ad_clone, "resolve_preset", None)
    if kind != gate.KIND_CLONE or not callable(resolve):
        return payload
    name = resolve(session, row.user_id, brand=_sections(session, row), space_id=row.space_id)
    return {**payload, "preset": name} if name else payload


def _sections(session: Any, row: AgentSession) -> dict[str, Any]:
    return memory.current(session, row.space_id)["sections"]


def _first_url(text: str) -> str:
    match = _URL_RE.search(text)
    return match.group(0).rstrip(".,;") if match else ""


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def _setup(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    url = _first_url(text)
    if not url:
        return [_say(session, row, "Paste your website address (starting with https://) and I'll read it.")]
    space = spaces.get(session, row.user_id, row.space_id)
    return setup_flow.start(session, deps, row, space, url)


def _routine(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    rule = routines.parse_schedule(text)
    if rule is None:
        return [_say(session, row, "Tell me how often, for example \"3 new ad variations every Monday\".")]
    try:
        created = routines.create(session, row.user_id, row.space_id, name=text[:120], skill=rule["skill"],
                                  count=rule["count"], weekday=rule["weekday"], hour=rule["hour"], now=deps.now())
    except routines.RoutineError as exc:
        return [_say(session, row, exc.message)]
    return [_say(session, row,
                 f"Scheduled: {routines.describe(rule)}. Each run waits for you to approve it before anything "
                 f"is made or posted.", card={"type": "routine", "data": created})]


def _inspiration(session: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    url = _first_url(text)
    if not url:
        return [_say(session, row, "Paste the ad or TikTok link you want to keep.")]
    try:
        item = inspirations.add(session, row.user_id, row.space_id, url, source="user")
    except inspirations.InspirationError as exc:
        return [_say(session, row, exc.message)]
    return [_say(session, row, "Saved to Inspirations. Say \"clone it\" when you want a version for your brand.",
                 card={"type": "inspiration", "data": item})]


def _clone(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    url = _first_url(text)
    if not url:
        saved = inspirations.list_items(session, row.user_id, row.space_id)
        url = saved[0]["url"] if saved else ""
    if not url:
        return [_say(session, row, "Paste the TikTok or Meta ad link you want to clone.")]
    try:
        inspirations.add(session, row.user_id, row.space_id, url, source="agent")
    except inspirations.InspirationError as exc:
        return [_say(session, row, exc.message)]
    return [_propose(session, deps, row, kind=gate.KIND_CLONE, title=f"Clone ad from {url[:120]}",
                     payload={"url": url}, explain="I'll rebuild that ad for your brand with Ad Clone.")]


def _hooks(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    match = _COUNT_RE.search(text)
    count = int(match.group(1)) if match else 5
    platform = next((label for word, label in (("tiktok", "TikTok"), ("instagram", "Instagram"),
                                               ("youtube", "YouTube")) if word in text.lower()), "TikTok")
    lines = writers.hooks(_sections(session, row), count=count, platform=platform, llm=deps.llm)
    return [_say(session, row, f"{len(lines)} hooks for {platform}:",
                 card={"type": "hooks", "data": {"hooks": lines, "platform": platform}})]


def _script(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    match = _SECONDS_RE.search(text)
    data = writers.script(_sections(session, row), seconds=int(match.group(1)) if match else 30, llm=deps.llm)
    return [_say(session, row, f"A {data['seconds']}-second script:", card={"type": "script", "data": data})]


def _audience(session: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    current = _sections(session, row).get(memory.SECTION_VOICE)
    if not current:
        return [_say(session, row, "Set up your brand first, then I can change the audience.")]
    revised = proposals.apply_feedback(memory.SECTION_VOICE, current, text)
    saved = memory.write(session, row.user_id, row.space_id, memory.SECTION_VOICE, revised,
                         source=memory.SOURCE_USER)
    names = ", ".join(seg["name"] for seg in saved["data"]["segments"])
    return [_say(session, row, f"Updated your audience in brand memory (version {saved['version']}): {names}.",
                 card={"type": "memory", "data": saved})]


def _publish(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    lowered = text.lower()
    platforms = list(dict.fromkeys(p for word, p in _PLATFORMS if word in lowered)) or ["tiktok"]
    videos = [i for i in library.list_items(session, row.user_id, row.space_id) if i["kind"] == "video"]
    payload = {"platforms": platforms, "job_id": videos[0]["ref"] if videos else "", "text": text[:500]}
    target = ", ".join(platforms)
    what = f"your latest video ({videos[0]['title']})" if videos else "your latest finished video"
    return [_propose(session, deps, row, kind=gate.KIND_PUBLISH, title=f"Publish to {target}", payload=payload,
                     explain=f"I'll schedule {what} on {target} in 10 minutes.")]


def _image(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    return [_propose(session, deps, row, kind=gate.KIND_IMAGE, title=text[:200], payload={"prompt": text, "options": {}},
                     explain="I'll make an image ad from your brand memory.")]


def _video(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    match = _SECONDS_RE.search(text)
    seconds = max(5, min(int(match.group(1)) if match else 10, 60))
    options = {"duration": seconds, "aspect_ratio": "9:16"}
    return [_propose(session, deps, row, kind=gate.KIND_VIDEO, title=text[:200],
                     payload={"prompt": text, "options": options},
                     explain=f"I'll make a {seconds}-second vertical video ad from your brand memory.")]


def _answer(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    if deps.llm is None:
        return [_say(session, row, HELP_TEXT)]
    import json

    prompt = (f"BRAND MEMORY: {json.dumps(_sections(session, row))[:8000]}\nUSER: {text}\n"
              "Answer briefly. If they ask for something that spends credits or publishes, tell them to ask for "
              "it directly so you can propose it for approval.")
    reply = deps.llm.complete(copy_rules.SYSTEM_PROMPT, prompt).strip()
    return [_say(session, row, reply or HELP_TEXT)]


def _route(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    if setup_flow.awaiting_edit(row):
        return setup_flow.revise_from_text(session, deps, row, text)
    has_memory = bool(_sections(session, row))
    url = _first_url(text)
    if _SETUP_RE.search(text) or (url and not has_memory and not _CLONE_RE.search(text)
                                  and inspirations.kind_of(url) == "link"):
        return _setup(session, deps, row, text)
    if _ROUTINE_RE.search(text):
        return _routine(session, deps, row, text)
    if _INSPIRATION_RE.search(text):
        return _inspiration(session, row, text)
    if _CLONE_RE.search(text):
        return _clone(session, deps, row, text)
    if _HOOK_RE.search(text):
        return _hooks(session, deps, row, text)
    if _SCRIPT_RE.search(text):
        return _script(session, deps, row, text)
    if _AUDIENCE_RE.search(text):
        return _audience(session, row, text)
    if _PUBLISH_RE.search(text):
        return _publish(session, deps, row, text)
    if _IMAGE_RE.search(text):
        return _image(session, deps, row, text)
    if _VIDEO_RE.search(text):
        return _video(session, deps, row, text)
    return _answer(session, deps, row, text)


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
class AgentError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def handle_text(session: Any, deps: Any, user_id: str, session_id: str, text: str) -> list[dict[str, Any]]:
    row = sessions.get(session, user_id, session_id)
    value = str(text or "").strip()[:MAX_TEXT]
    if not value:
        raise AgentError("Type a message first.", 422)
    sessions.add_message(session, row, sessions.ROLE_USER, value)
    return _views(session, user_id, _route(session, deps, row, value))


def _recheck(session: Any, deps: Any, row: AgentSession, action_id: str, *,
             payload_update: dict[str, Any] | None = None, prefix: str = "") -> list[AgentMessage]:
    """Re-run the preflight for a blocked action: Approve when it is ready, else point back."""
    current = gate.views_by_id(session, row.user_id, [action_id]).get(action_id)
    if current is None:
        raise AgentError("That step is no longer open.", 404)
    payload = {**current["payload"], **(payload_update or {})}
    needs = preflight.check(session, deps, row.user_id, row.space_id, current["kind"], payload,
                            _sections(session, row))
    if not needs:
        payload_update = {**(payload_update or {}),
                          **{k: v for k, v in _with_preset(session, deps, row, current["kind"], payload).items()
                             if k == "preset"}}
    action = gate.set_needs(session, row.user_id, action_id, needs, payload_update)
    if not needs:
        return [_ready_message(session, row, action, f"{prefix}Ready.".strip())]
    if [n["id"] for n in needs] == [n["id"] for n in current.get("needs") or []]:
        return [_say(session, row, f"{prefix}Still waiting on the step above: {needs[0]['title']}".strip())]
    return [_blocked_message(session, row, action, prefix.strip() or "One more thing.")]


def _use_product(session: Any, deps: Any, row: AgentSession, action_id: str, product_id: str) -> list[AgentMessage]:
    use = getattr(deps.ad_clone, "use_product", None)
    if not callable(use) or not product_id:
        raise AgentError("Pick one of the products above.")
    space = spaces.get(session, row.user_id, row.space_id)
    try:
        made = use(session, row.user_id, space_id=row.space_id, product_id=product_id,
                   brand=_sections(session, row), brand_name=space.name if space.name != "My brand" else "",
                   website=space.website_url)
    except PortUnavailable as exc:
        return [_say(session, row, exc.reason)]
    return _recheck(session, deps, row, action_id, payload_update={"preset": made["preset"]},
                    prefix=f"Set up {made['product']} in Ad Clone. ")


def handle_chip(session: Any, deps: Any, user_id: str, session_id: str, *, step: str = "", choice: str,
                edits: dict[str, Any] | None = None, action_id: str | None = None,
                value: str | None = None) -> list[dict[str, Any]]:
    row = sessions.get(session, user_id, session_id)
    if action_id and choice in ("use_product", "recheck"):
        label = "Use this product" if choice == "use_product" else "Check again"
        sessions.add_message(session, row, sessions.ROLE_USER, label)
        if choice == "use_product":
            return _views(session, user_id, _use_product(session, deps, row, action_id, str(value or "")))
        return _views(session, user_id, _recheck(session, deps, row, action_id))
    if action_id:
        decision = {"approve": gate.APPROVE, "reject": gate.REJECT}.get(choice)
        if decision is None:
            raise AgentError("Choose Approve or Reject.")
        sessions.add_message(session, row, sessions.ROLE_USER, "Approve" if decision == gate.APPROVE else "Reject")
        before = gate.views_by_id(session, user_id, [action_id]).get(action_id) or {}
        result = gate.decide(session, deps, user_id, action_id, decision)
        if result["status"] == gate.STATUS_BLOCKED and before.get("status") == gate.STATUS_BLOCKED:
            first = result["needs"][0] if result["needs"] else {"title": "the step above"}
            return _views(session, user_id, [_say(session, row, f"Still waiting on the step above: {first['title']}")])
        if result["status"] == gate.STATUS_BLOCKED:
            first = result["needs"][0] if result["needs"] else {"title": "the step above"}
            reply = _say(session, row, f"Not yet: {first['title']}", chips=preflight.chips(action_id, result["needs"]),
                         action_id=action_id, card={"type": "action", "data": result})
            return _views(session, user_id, [reply])
        text = {
            gate.STATUS_EXECUTED: "Done. It's in your Library.",
            gate.STATUS_REJECTED: "Rejected. Nothing was made or posted.",
            gate.STATUS_FAILED: f"That didn't work: {result['error']}",
        }.get(result["status"], "Working on it.")
        reply = _say(session, row, text, action_id=action_id, card={"type": "action", "data": result})
        return _views(session, user_id, [reply])
    labels = {"yes": "Yes", "no": "No, change it", "connect": "Connect Meta Ads", "retry": "Retry",
              "skip": "Skip for now"}
    sessions.add_message(session, row, sessions.ROLE_USER, labels.get(choice, choice)[:80])
    space = spaces.get(session, user_id, row.space_id)
    replies = setup_flow.answer(session, deps, row, space, step=step, choice=choice, edits=edits)
    return _views(session, user_id, replies)


__all__ = ["AgentError", "HELP_TEXT", "handle_chip", "handle_text"]
