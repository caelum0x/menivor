"""Brand setup step machine: analyze -> confirm each section -> optional Meta Ads -> done.

State lives in ``AgentSession.state["setup"]`` (replaced, never mutated):

    {"step", "url", "analysis", "proposals": {section: draft}, "awaiting_edit": section | None}

Steps: positioning -> product -> market -> voice_audience -> connect_meta -> done.
A section is written to brand memory only after the user's Yes (or an explicit
edit). "No, change it" asks what should change; the next message revises the
draft (LLM through Relay when configured, deterministic otherwise) and shows it
again for a Yes. Connecting Meta Ads is optional and its failures are explained
with a Retry, never raised.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.domains.brand_agent import inspirations, memory, proposals, sessions, spaces
from app.domains.brand_agent.models import AgentBrandSpace, AgentMessage, AgentSession
from app.domains.brand_agent.ports.base import PortUnavailable
from app.domains.brand_agent.site_analysis import SiteAnalysisError

STEP_POSITIONING = memory.SECTION_POSITIONING
STEP_PRODUCT = memory.SECTION_PRODUCT
STEP_MARKET = memory.SECTION_MARKET
STEP_VOICE = memory.SECTION_VOICE
STEP_META = "connect_meta"
STEP_DONE = "done"
SECTION_STEPS: tuple[str, ...] = (STEP_POSITIONING, STEP_PRODUCT, STEP_MARKET, STEP_VOICE)
ORDER: tuple[str, ...] = (*SECTION_STEPS, STEP_META, STEP_DONE)

TITLES = {
    STEP_POSITIONING: "Positioning",
    STEP_PRODUCT: "Product",
    STEP_MARKET: "Market",
    STEP_VOICE: "Voice and audience",
    STEP_META: "Connect Meta Ads?",
}
YES, NO, CONNECT, RETRY, SKIP = "yes", "no", "connect", "retry", "skip"
META_LIMIT = 6
SEARCH_LIMIT = 6
DONE_TEXT = ("Your brand is set up. I can write scripts and hooks, make images and videos, clone an ad from a "
             "link, or schedule a routine. Anything that spends credits or publishes waits for your approval.")


class SetupError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def state_of(row: AgentSession) -> dict[str, Any]:
    return dict((row.state or {}).get("setup") or {})


def _save_state(session: Any, row: AgentSession, setup: dict[str, Any]) -> None:
    sessions.set_state(session, row, {**(row.state or {}), "setup": setup})


def awaiting_edit(row: AgentSession) -> str | None:
    return state_of(row).get("awaiting_edit") or None


def in_progress(row: AgentSession) -> bool:
    step = state_of(row).get("step")
    return bool(step) and step != STEP_DONE


def _step_chips(step: str) -> list[dict[str, str]]:
    return [{"label": "Yes, save it", "choice": YES, "step": step},
            {"label": "No, change it", "choice": NO, "step": step}]


def _meta_chips(retry: bool = False) -> list[dict[str, str]]:
    first = {"label": "Retry", "choice": RETRY, "step": STEP_META} if retry else \
        {"label": "Connect Meta Ads", "choice": CONNECT, "step": STEP_META}
    return [first, {"label": "Skip for now", "choice": SKIP, "step": STEP_META}]


def _card(step: str, data: dict[str, Any]) -> dict[str, Any]:
    index = SECTION_STEPS.index(step) + 1 if step in SECTION_STEPS else None
    return {"type": "setup_step", "step": step, "title": TITLES.get(step, step), "data": data,
            "index": index, "total": len(SECTION_STEPS)}


_PROMPTS = {
    STEP_POSITIONING: "Here is how I read your positioning. Is this right?",
    STEP_PRODUCT: "Here is your product as your site describes it. Is this right?",
    STEP_MARKET: "Here is the market I found. Is this right?",
    STEP_VOICE: "Here is your voice and who you speak to. Is this right?",
}


def _ask(session: Any, row: AgentSession, step: str, data: dict[str, Any], *, revised: bool = False) -> AgentMessage:
    text = f"I updated {TITLES[step]}. Is it right now?" if revised else _PROMPTS[step]
    return sessions.add_message(session, row, sessions.ROLE_ASSISTANT, text, card=_card(step, data),
                                chips=_step_chips(step))


def _ask_meta(session: Any, row: AgentSession) -> AgentMessage:
    text = ("Connect Meta Ads? I'll pull your top-performing ads into Inspirations so new creatives start "
            "from what already works. You can skip this.")
    card = {"type": "connect", "step": STEP_META, "title": TITLES[STEP_META], "data": {"platform": "meta"}}
    return sessions.add_message(session, row, sessions.ROLE_ASSISTANT, text, card=card, chips=_meta_chips())


def _summary(analysis: dict[str, Any], results: list[dict[str, str]], search_enabled: bool) -> str:
    colors = ", ".join(c["hex"] for c in analysis.get("colors", [])[:4]) or "none found"
    fonts = ", ".join(f["family"] for f in analysis.get("fonts", [])[:3]) or "none found"
    logo = "found" if (analysis.get("logo") or {}).get("origin") else "not found"
    search = (f"searched the web for your market ({len(results)} results)" if search_enabled
              else "web search is off on this server, so the market step uses your site only")
    return (f"I read {analysis.get('website_url', '')}: {analysis.get('name') or 'your site'}, "
            f"{analysis.get('category', '')}. Colors: {colors}. Fonts: {fonts}. Logo: {logo}. "
            f"I also {search}. Let's confirm each part; I save it to brand memory after your Yes.")


def start(session: Any, deps: Any, row: AgentSession, space: AgentBrandSpace, url: str) -> list[AgentMessage]:
    try:
        analysis = deps.analyzer(url)
    except SiteAnalysisError as exc:
        return [sessions.add_message(session, row, sessions.ROLE_ASSISTANT,
                                     f"I couldn't read that site: {exc.message}.")]
    search_enabled = bool(getattr(deps.search, "enabled", True))
    results: list[dict[str, str]] = []
    for query in proposals.market_queries(analysis):
        try:
            results.extend(deps.search.search(query, limit=SEARCH_LIMIT))
        except Exception as exc:  # noqa: BLE001 - search is optional
            logger.warning(f"brand agent market search failed: {type(exc).__name__}")
    drafts = proposals.build_all(analysis, results, search_enabled=search_enabled)
    drafts = proposals.enrich(deps.llm, analysis, results, drafts)
    spaces.rename_from_brand(session, space, name=analysis.get("name", ""), website_url=url)
    slim = {k: analysis.get(k) for k in ("name", "website_url", "category", "sample_lines", "features",
                                          "description", "one_liner", "headings")}
    _save_state(session, row, {"step": STEP_POSITIONING, "url": url, "analysis": slim, "proposals": drafts,
                               "awaiting_edit": None})
    return [
        sessions.add_message(session, row, sessions.ROLE_ASSISTANT, _summary(analysis, results, search_enabled)),
        _ask(session, row, STEP_POSITIONING, drafts[STEP_POSITIONING]),
    ]


def _advance(session: Any, row: AgentSession, setup: dict[str, Any], step: str) -> list[AgentMessage]:
    nxt = ORDER[ORDER.index(step) + 1]
    _save_state(session, row, {**setup, "step": nxt, "awaiting_edit": None})
    if nxt in SECTION_STEPS:
        return [_ask(session, row, nxt, setup["proposals"][nxt])]
    return [_ask_meta(session, row)]


def _save_section(session: Any, row: AgentSession, space: AgentBrandSpace, setup: dict[str, Any], step: str,
                  data: dict[str, Any], source: str) -> list[AgentMessage]:
    saved = memory.write(session, row.user_id, space.id, step, data, source=source)
    setup = {**setup, "proposals": {**setup["proposals"], step: saved["data"]}}
    note = sessions.add_message(session, row, sessions.ROLE_ASSISTANT,
                                f"Saved {TITLES[step]} to brand memory (version {saved['version']}).")
    return [note, *_advance(session, row, setup, step)]


def _connect_meta(session: Any, deps: Any, row: AgentSession, space: AgentBrandSpace,
                  setup: dict[str, Any]) -> list[AgentMessage]:
    try:
        creatives = deps.integrations.top_performing_creatives(row.user_id, platform="meta", limit=META_LIMIT)
    except PortUnavailable as exc:
        reason = exc.reason
    except Exception as exc:  # noqa: BLE001 - never echo raw upstream errors
        logger.warning(f"brand agent meta connect failed: {type(exc).__name__}")
        reason = "Meta did not answer. Check the ad account in Connectors and try again in a minute."
    else:
        saved = inspirations.save_creatives(session, row.user_id, space.id, creatives, source="meta_ads")
        _save_state(session, row, {**setup, "step": STEP_DONE})
        noun = "ad" if saved == 1 else "ads"
        return [sessions.add_message(
            session, row, sessions.ROLE_ASSISTANT,
            f"Saved {saved} top-performing {noun} from Meta Ads to Inspirations. {DONE_TEXT}")]
    return [sessions.add_message(session, row, sessions.ROLE_ASSISTANT, f"Couldn't connect Meta Ads: {reason}",
                                 chips=_meta_chips(retry=True))]


def answer(session: Any, deps: Any, row: AgentSession, space: AgentBrandSpace, *, step: str, choice: str,
           edits: dict[str, Any] | None = None) -> list[AgentMessage]:
    setup = state_of(row)
    current = setup.get("step")
    if not current:
        raise SetupError("Start by telling me your website.", 409)
    if step != current:
        raise SetupError("That question was already answered.", 409)
    if step == STEP_META:
        if choice in {CONNECT, RETRY}:
            return _connect_meta(session, deps, row, space, setup)
        if choice == SKIP:
            _save_state(session, row, {**setup, "step": STEP_DONE})
            return [sessions.add_message(session, row, sessions.ROLE_ASSISTANT,
                                         f"Skipped Meta Ads; you can connect it later in Connectors. {DONE_TEXT}")]
        raise SetupError("Choose Connect, Retry or Skip.", 400)
    if step not in SECTION_STEPS:
        raise SetupError("Setup is already finished.", 409)
    proposal = setup["proposals"][step]
    if edits:
        merged = {**proposal, **{k: v for k, v in edits.items() if k in proposal}}
        return _save_section(session, row, space, setup, step, merged, memory.SOURCE_USER)
    if choice == YES:
        # A draft the user corrected is their own edit: it never lights the Brain badge.
        source = memory.SOURCE_USER if step in (setup.get("edited") or []) else memory.SOURCE_AGENT
        return _save_section(session, row, space, setup, step, proposal, source)
    if choice == NO:
        _save_state(session, row, {**setup, "awaiting_edit": step})
        return [sessions.add_message(
            session, row, sessions.ROLE_ASSISTANT,
            f"What should change in {TITLES[step]}? Tell me in your words, or edit the fields directly.")]
    raise SetupError("Choose Yes or No.", 400)


def revise_from_text(session: Any, deps: Any, row: AgentSession, text: str) -> list[AgentMessage]:
    setup = state_of(row)
    step = setup.get("awaiting_edit")
    revised = proposals.revise(deps.llm, step, setup["proposals"][step], text)
    edited = sorted({*(setup.get("edited") or []), step})
    _save_state(session, row, {**setup, "awaiting_edit": None, "edited": edited,
                               "proposals": {**setup["proposals"], step: revised}})
    return [_ask(session, row, step, revised, revised=True)]


__all__ = [
    "DONE_TEXT",
    "ORDER",
    "SECTION_STEPS",
    "STEP_DONE",
    "STEP_MARKET",
    "STEP_META",
    "STEP_POSITIONING",
    "STEP_PRODUCT",
    "STEP_VOICE",
    "SetupError",
    "answer",
    "awaiting_edit",
    "in_progress",
    "revise_from_text",
    "start",
    "state_of",
]
