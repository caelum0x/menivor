"""Tools of the hosted Menivor MCP connector.

Every tool runs as the token's user (and workspace). Spending is never done here:
``generate_image`` / ``generate_video`` only create pending Brand Agent actions and
return the link where a person approves them; there is no approve tool. Ad Clone
tools are the $0 steps (local analysis, priced plans), never a paid render.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from app.domains.adstudio.extract import clean_text


class ToolError(Exception):
    """A tool refused or failed; the message is safe to show to the agent."""


@dataclass
class ToolContext:
    session: Any
    user_id: str
    workspace_id: str | None
    scopes: tuple[str, ...]
    web_url: str = "https://menivor.com"
    overrides: dict[str, Callable[..., Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    scope: str
    run: Callable[[ToolContext, dict[str, Any]], Any]
    spends: bool = False
    # Optional runtime switch: the tool is neither listed nor callable while it returns False.
    enabled: Callable[[], bool] | None = None

    def on(self) -> bool:
        return self.enabled is None or bool(self.enabled())


def _space(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.brand_agent import spaces

    try:
        return spaces.resolve(ctx.session, ctx.user_id, str(args.get("space_id") or "") or None)
    except spaces.SpaceError as exc:
        raise ToolError(exc.message) from exc


def _brand_memory_get(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.brand_agent import memory

    space = _space(ctx, args)
    return {"space": {"id": space.id, "name": space.name}, **memory.current(ctx.session, space.id)}


def _brand_memory_update(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.brand_agent import memory

    section = str(args.get("section") or "")
    if section not in memory.SECTIONS:
        raise ToolError(f"section must be one of {', '.join(memory.SECTIONS)}")
    if not isinstance(args.get("data"), dict):
        raise ToolError("data must be an object with the section's fields")
    space = _space(ctx, args)
    try:
        out = memory.write(ctx.session, ctx.user_id, space.id, section, args["data"], source=memory.SOURCE_USER)
    except memory.MemoryError_ as exc:
        raise ToolError(exc.message) from exc
    return {"saved": True, "version": out.get("version"), "section": section}


def _adclone_on() -> None:
    from app.domains.adclone import service

    if not service.enabled():
        raise ToolError("Ad Clone is switched off on this server.")


def _ad_clone_brief(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.adclone import service

    url = clean_text(args.get("url"), 500)
    if not url:
        raise ToolError("url is required")
    analyze = ctx.overrides.get("analyze_link")
    if analyze is None:
        _adclone_on()
        analyze = service.analyze_link
    try:
        brief = analyze(url, llm=service.default_llm() if "analyze_link" not in ctx.overrides else None)
    except Exception as exc:  # noqa: BLE001 - typed Ad Clone errors carry a safe message
        raise ToolError(getattr(exc, "message", "") or "could not read that ad") from exc
    return {"brief": brief.model_dump() if hasattr(brief, "model_dump") else brief, "spent": 0}


def _ad_clone_plan(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.adclone import service
    from app.domains.adclone.rewrite import CloneOptions
    from app.domains.adclone.schemas import CloneBrief

    plan = ctx.overrides.get("clone")
    if plan is None:
        _adclone_on()
        plan = service.clone
    try:
        brief = CloneBrief.model_validate(args.get("brief") or {})
        result = plan(brief, preset_name=str(args.get("product") or "oxhan")[:24],
                      options=CloneOptions(variations=max(1, min(int(args.get("variations") or 1), 3))))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(getattr(exc, "message", "") or "could not plan that clone") from exc
    rows = [{"slug": v["plan"].get("slug"), "engine": v["engine"].get("engine"), "usd": v["engine"].get("usd"),
             "ai_video_credits": v.get("ai_video_credits")} for v in result.get("variations") or []]
    return {"variations": rows, "next": f"Approve a render on {ctx.web_url}/ad-clone (paid renders need a person)."}


def _generate(kind: str) -> Callable[[ToolContext, dict[str, Any]], Any]:
    def run(ctx: ToolContext, args: dict[str, Any]) -> Any:
        from app.domains.brand_agent import gate

        prompt = clean_text(args.get("prompt"), 2000)
        if not prompt:
            raise ToolError("prompt is required")
        count = max(1, min(int(args.get("count") or 1), 5))
        space = _space(ctx, args)
        payload = {"prompt": prompt, "requested_via": "mcp"}
        if count > 1:
            action = gate.propose(ctx.session, ctx.user_id, space.id, None, kind=gate.KIND_ROUTINE_BATCH,
                                  title=f"{count} {kind}s from your agent", payload={
                                      **payload, "count": count, "media": kind, "skill": "ad_variations"})
        else:
            action = gate.propose(ctx.session, ctx.user_id, space.id, None,
                                  kind=gate.KIND_VIDEO if kind == "video" else gate.KIND_IMAGE,
                                  title=f"{kind.capitalize()} from your agent", payload=payload)
        return {"status": "pending_approval", "action_id": action["id"], "credits_estimate": action["credits_estimate"],
                "approve_url": f"{ctx.web_url}/agent", "note": "Nothing was spent. A person approves this in Menivor."}

    return run


def _approvals_list(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.approvals import service as approvals
    from app.domains.brand_agent import gate

    status = str(args.get("status") or "pending")
    feed = approvals.list_items(ctx.user_id, status=status if status in ("pending", "all") else "pending", limit=50)
    agent = gate.list_actions(ctx.session, ctx.user_id, status=gate.STATUS_PENDING if status == "pending" else None)
    return {"approvals": [{k: i[k] for k in ("id", "source", "title", "status", "risk")} for i in feed["items"]],
            "agent_actions": [{k: a[k] for k in ("id", "kind", "title", "status", "credits_estimate")} for a in agent],
            "approve_in": f"{ctx.web_url}/approvals"}


def _scope(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.integrations.errors import IntegrationError
    from app.domains.integrations.scope import resolve

    try:
        return resolve(ctx.session, ctx.user_id, workspace_id=ctx.workspace_id,
                       brand_space_id=str(args.get("brand_space_id") or "") or None)
    except IntegrationError as exc:
        raise ToolError(exc.message) from exc


def _analytics_report(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.integrations import agent

    try:
        return agent.pull_report(ctx.session, _scope(ctx, args), ad_account_id=args.get("ad_account_id") or None,
                                 days=max(1, min(int(args.get("days") or 7), 90)))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(getattr(exc, "message", "") or "could not read the report") from exc


def _ad_fatigue(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.ad_fatigue import service

    try:
        out = service.report(ctx.session, _scope(ctx, args), ad_account_id=args.get("ad_account_id") or None,
                             days=max(7, min(int(args.get("days") or 14), 60)))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(getattr(exc, "message", "") or "could not read fatigue") from exc
    for c in out["creatives"]:
        c.pop("series", None)
    return out


def _competitor_winners(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.competitors import service

    try:
        ads = service.list_ads(ctx.session, ctx.user_id, brand_id=args.get("brand_id") or None,
                               limit=max(1, min(int(args.get("limit") or 10), 50)))
    except service.CompetitorError as exc:
        raise ToolError(exc.message) from exc
    keep = ("id", "brand_name", "source", "advertiser", "title", "body", "page_url", "days_running", "tier", "score")
    return {"ads": [{k: a[k] for k in keep} for a in ads]}


def _launch_platforms(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.launch_kit import service

    try:
        return service.list_launch_platforms(ctx.session, ctx.user_id, product_name=args.get("product_name") or None,
                                             product_category=args.get("product_category") or None)
    except service.LaunchKitError as exc:
        raise ToolError(exc.message) from exc


def _launch_set_platform_status(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.launch_kit import service

    product_name = clean_text(args.get("product_name"), 200)
    platform_id = str(args.get("platform_id") or "").strip()
    if not product_name or not platform_id:
        raise ToolError("product_name and platform_id are required")
    try:
        return service.set_platform_status(ctx.session, ctx.user_id, product_name=product_name,
                                           platform_id=platform_id, status=str(args.get("status") or ""),
                                           note=str(args.get("note") or ""))
    except service.LaunchKitError as exc:
        raise ToolError(exc.message) from exc


def _launch_pain_points(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.launch_kit import service

    query = clean_text(args.get("query"), 300)
    if not query:
        raise ToolError("query is required")
    subs = [str(s)[:100] for s in (args.get("subreddits") or []) if str(s or "").strip()][:10]
    try:
        return service.find_pain_point_threads(ctx.session, ctx.user_id, query=query, subreddits=subs or None,
                                               product_name=str(args.get("product_name") or ""),
                                               limit=max(1, min(int(args.get("limit") or 10), 25)))
    except service.LaunchKitError as exc:
        raise ToolError(exc.message) from exc


def _launch_backlinks(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.launch_kit import service

    domain = str(args.get("domain") or "").strip()
    if not domain:
        raise ToolError("domain is required")
    try:
        return service.find_competitor_backlinks(domain, allow_live=bool(args.get("allow_live") or False))
    except service.LaunchKitError as exc:
        raise ToolError(exc.message) from exc


def _launch_checklist(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.launch_kit import service

    product_name = clean_text(args.get("product_name"), 200)
    if not product_name:
        raise ToolError("product_name is required")
    try:
        return service.get_launch_checklist(ctx.session, ctx.user_id, product_name=product_name)
    except service.LaunchKitError as exc:
        raise ToolError(exc.message) from exc


def _launch_mark_step(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from app.domains.launch_kit import service

    product_name = clean_text(args.get("product_name"), 200)
    step_key = str(args.get("step_key") or "").strip()
    if not product_name or not step_key:
        raise ToolError("product_name and step_key are required")
    try:
        return service.mark_playbook_step(ctx.session, ctx.user_id, product_name=product_name, step_key=step_key,
                                          status=str(args.get("status") or ""), note=str(args.get("note") or ""))
    except service.LaunchKitError as exc:
        raise ToolError(exc.message) from exc


def _presets_live() -> bool:
    from app.mcp import presets_tools

    return presets_tools.live()


def _presets_call(name: str) -> Callable[[ToolContext, dict[str, Any]], Any]:
    """Run a shelf tool from :mod:`app.mcp.presets_tools` (the stdio server's handlers)."""

    def run(ctx: ToolContext, args: dict[str, Any]) -> Any:
        from app.mcp import presets_tools
        from app.mcp.tools import MCPToolError

        try:
            return presets_tools.dispatch(ctx.session, ctx.user_id, name, args)
        except MCPToolError as exc:
            raise ToolError(str(exc)) from exc

    return run


_OBJ = {"type": "object", "additionalProperties": False}
_SPACE = {"space_id": {"type": "string", "description": "Brand space id (default: your first brand)."}}

TOOLS: tuple[Tool, ...] = (
    Tool("brand_memory_get", "Read the brand memory (positioning, product, market, voice and audience).",
         {**_OBJ, "properties": _SPACE}, "read", _brand_memory_get),
    Tool("brand_memory_update", "Save a new version of one brand memory section (it is versioned, never lost).",
         {**_OBJ, "properties": {**_SPACE, "section": {"type": "string", "enum": ["positioning", "product", "market",
                                                                                 "voice_audience"]},
                                 "data": {"type": "object"}}, "required": ["section", "data"]},
         "write", _brand_memory_update),
    Tool("ad_clone_brief", "Analyse a winning ad link (TikTok, YouTube, Vimeo, X) into a clone brief. Free.",
         {**_OBJ, "properties": {"url": {"type": "string"}}, "required": ["url"]}, "write", _ad_clone_brief),
    Tool("ad_clone_plan", "Turn a clone brief into priced clone plans for a product. Free; renders need approval.",
         {**_OBJ, "properties": {"brief": {"type": "object"}, "product": {"type": "string"},
                                 "variations": {"type": "integer", "minimum": 1, "maximum": 3}},
          "required": ["brief"]}, "write", _ad_clone_plan),
    Tool("generate_image", "Ask for ad images. Creates a pending approval; nothing is spent until a person approves.",
         {**_OBJ, "properties": {**_SPACE, "prompt": {"type": "string"},
                                 "count": {"type": "integer", "minimum": 1, "maximum": 5}}, "required": ["prompt"]},
         "write", _generate("image"), spends=True),
    Tool("generate_video", "Ask for a video. Creates a pending approval; nothing is spent until a person approves.",
         {**_OBJ, "properties": {**_SPACE, "prompt": {"type": "string"},
                                 "count": {"type": "integer", "minimum": 1, "maximum": 5}}, "required": ["prompt"]},
         "write", _generate("video"), spends=True),
    Tool("approvals_list", "List what is waiting for a person to approve (approve in the Menivor app).",
         {**_OBJ, "properties": {"status": {"type": "string", "enum": ["pending", "all"]}}}, "read", _approvals_list),
    Tool("analytics_report", "Ad performance from connected ad accounts: totals and per-creative rows.",
         {**_OBJ, "properties": {"ad_account_id": {"type": "string"}, "brand_space_id": {"type": "string"},
                                 "days": {"type": "integer", "minimum": 1, "maximum": 90}}}, "read",
         _analytics_report),
    Tool("ad_fatigue", "Fatigue per creative: frequency, CTR decay, CPA drift and a 0-100 score.",
         {**_OBJ, "properties": {"ad_account_id": {"type": "string"}, "brand_space_id": {"type": "string"},
                                 "days": {"type": "integer", "minimum": 7, "maximum": 60}}}, "read", _ad_fatigue),
    Tool("competitor_winners", "Tracked competitor ads ranked by how long they have run (the winner signal).",
         {**_OBJ, "properties": {"brand_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1,
                                                                            "maximum": 50}}}, "read",
         _competitor_winners),
    Tool("list_launch_platforms", "Curated launch directories (Product Hunt, DevHunt, BetaList, Peerlist, "
         "Show HN and more), optionally filtered by category, with this product's submission state.",
         {**_OBJ, "properties": {"product_name": {"type": "string"}, "product_category": {
             "type": "string", "enum": ["saas", "ai", "app", "dev_tool", "oss", "general"]}}}, "read",
         _launch_platforms),
    Tool("set_launch_platform_status", "Record what you actually submitted on a launch directory "
         "(not_started/submitted/live). This never submits anything itself -- it only remembers what a "
         "person did.",
         {**_OBJ, "properties": {"product_name": {"type": "string"}, "platform_id": {"type": "string"},
                                 "status": {"type": "string", "enum": ["not_started", "submitted", "live"]},
                                 "note": {"type": "string"}},
          "required": ["product_name", "platform_id", "status"]}, "write", _launch_set_platform_status),
    Tool("find_pain_point_threads", "Search Reddit (public, read-only) for threads about a pain point and "
         "draft a reply for each one. Drafts are saved for a person to review and post; nothing here posts "
         "to Reddit.",
         {**_OBJ, "properties": {"query": {"type": "string"}, "subreddits": {"type": "array",
                                                                             "items": {"type": "string"}},
                                 "product_name": {"type": "string"},
                                 "limit": {"type": "integer", "minimum": 1, "maximum": 25}},
          "required": ["query"]}, "write", _launch_pain_points),
    Tool("find_competitor_backlinks", "Where a competitor domain is linked/listed, so you submit there too. "
         "Free fallback (general launch directories) unless a DataForSEO key is configured AND allow_live "
         "is explicitly set -- never spends credits on its own.",
         {**_OBJ, "properties": {"domain": {"type": "string"}, "allow_live": {"type": "boolean"}},
          "required": ["domain"]}, "read", _launch_backlinks),
    Tool("get_launch_checklist", "The 10-step first-100-users playbook for one product: which steps are "
         "done vs pending, backed by persisted state (not a static list).",
         {**_OBJ, "properties": {"product_name": {"type": "string"}}, "required": ["product_name"]}, "read",
         _launch_checklist),
    Tool("mark_playbook_step", "Mark one playbook step (e.g. cold_outreach, ugc_creators, build_in_public) "
         "done or pending for a product.",
         {**_OBJ, "properties": {"product_name": {"type": "string"}, "step_key": {"type": "string"},
                                 "status": {"type": "string", "enum": ["pending", "done"]},
                                 "note": {"type": "string"}},
          "required": ["product_name", "step_key", "status"]}, "write", _launch_mark_step),
    Tool("presets_list", "List the preset shelf: one-tap video looks and effects with preview loops. "
         "Optional kind: filter (standard credits) or model (AI-video credits).",
         {**_OBJ, "properties": {"kind": {"type": "string", "enum": ["filter", "model"]}}}, "read",
         _presets_call("presets.list"), enabled=_presets_live),
    Tool("presets_recreate", "Get the Create call for a preset (preset_id) or a public gallery item (item_id) "
         "with your own subject. Returns the route and body to post; nothing is charged by this tool.",
         {**_OBJ, "properties": {"preset_id": {"type": "string"}, "item_id": {"type": "string"},
                                 "subject": {"type": "string"}, "image_key": {"type": "string"}},
          "required": ["subject"]}, "read", _presets_call("presets.recreate"), enabled=_presets_live),
)
BY_NAME = {t.name: t for t in TOOLS}


def listing(scopes: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "inputSchema": t.schema,
             "annotations": {"readOnlyHint": t.scope == "read", "destructiveHint": False}}
            for t in TOOLS if t.scope in scopes and t.on()]


def call(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = BY_NAME.get(name)
    if tool is None or tool.scope not in ctx.scopes or not tool.on():
        raise ToolError(f"unknown tool: {name}")
    out = tool.run(ctx, dict(args or {}))
    text = json.dumps(out, ensure_ascii=False, default=str)
    return {"content": [{"type": "text", "text": text[:60_000]}], "structuredContent": out, "isError": False}


__all__ = ["BY_NAME", "TOOLS", "Tool", "ToolContext", "ToolError", "call", "listing"]
