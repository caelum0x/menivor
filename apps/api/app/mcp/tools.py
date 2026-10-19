"""In-process MCP tool registry + dispatch for ReelForge.

Each tool maps to a domain-service call scoped to the resolving user. The dispatch
is transport-agnostic (the stdio server and tests both call :func:`dispatch`),
so the agent surface is exercised without a running MCP client. Tools never
expose secrets, never spend money without the same guards the HTTP API uses, and
return plain JSON-safe dicts.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session


class MCPToolError(Exception):
    """A tool-level failure with a safe message (mapped to an MCP error)."""


# --------------------------------------------------------------------------- #
# Tool handlers — (session, user_id, args) -> dict
# --------------------------------------------------------------------------- #
def _list_models(session: Session, user_id: str, args: dict) -> dict:
    from app.domains.catalog.service import CatalogService

    capability = (args.get("capability") or "").strip() or None
    models = CatalogService(session).browse_models(capability=capability, limit=50)
    return {"models": models}


def _generation_quote(session: Session, user_id: str, args: dict) -> dict:
    from app.domains.catalog.schemas import GenerationQuoteRequest
    from app.domains.catalog.service import CatalogError, CatalogService

    req = GenerationQuoteRequest(
        profile=args.get("profile"),
        stages=args.get("stages"),
        max_cost_usd=args.get("max_cost_usd"),
    )
    try:
        return CatalogService(session).quote_generation(req, user_id=user_id)
    except CatalogError as exc:
        raise MCPToolError(exc.message) from exc


def _wallet_balance(session: Session, user_id: str, args: dict) -> dict:
    from app.domains.wallet.service import WalletService

    return WalletService(session).balance_view(user_id)


def _create_repurpose(session: Session, user_id: str, args: dict) -> dict:
    from app.domains.repurpose.service import RepurposeError, RepurposeService

    try:
        return RepurposeService(session).create_job(
            user_id,
            source_kind=str(args.get("source_kind", "url")),
            source_ref=str(args.get("source_ref", "")),
            language=str(args.get("language", "auto")),
            title=str(args.get("title", "")),
        )
    except RepurposeError as exc:
        raise MCPToolError(exc.message) from exc


def _get_job(session: Session, user_id: str, args: dict) -> dict:
    import importlib

    # The reels package re-exports the APIRouter as ``app.domains.reels.router``
    # (shadowing the submodule), so resolve the real module explicitly.
    reels_router = importlib.import_module("app.domains.reels.router")
    from app.models.db.repositories import JobRepository

    job_id = str(args.get("job_id", "")).strip()
    if not job_id:
        raise MCPToolError("job_id is required")
    job = JobRepository(session).get(job_id)
    if job is None or job.user_id != user_id:
        raise MCPToolError("job not found")
    return reels_router._job_public_data(job, "mcp")


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
TOOLS: list[dict[str, Any]] = [
    {
        "name": "reelforge_list_models",
        "description": "List reviewed generation models, optionally by capability "
        "(script|voice|avatar|broll|image|music).",
        "input_schema": {
            "type": "object",
            "properties": {"capability": {"type": "string"}},
        },
        "handler": _list_models,
    },
    {
        "name": "reelforge_generation_quote",
        "description": "Quote a generation from a profile slug or a stage->model map; "
        "returns a signed, versioned max-cost snapshot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string"},
                "stages": {"type": "object"},
                "max_cost_usd": {"type": "string"},
            },
        },
        "handler": _generation_quote,
    },
    {
        "name": "reelforge_wallet_balance",
        "description": "Get the caller's USD wallet balance (available + reserved).",
        "input_schema": {"type": "object", "properties": {}},
        "handler": _wallet_balance,
    },
    {
        "name": "reelforge_create_repurpose",
        "description": "Start a repurpose job from a long video URL or upload key.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_kind": {"type": "string", "enum": ["upload", "url"]},
                "source_ref": {"type": "string"},
                "language": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["source_ref"],
        },
        "handler": _create_repurpose,
    },
    {
        "name": "reelforge_get_job",
        "description": "Get a reel job's status/progress/result by id.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
        "handler": _get_job,
    },
]

_BY_NAME: dict[str, Callable[[Session, str, dict], dict]] = {
    t["name"]: t["handler"] for t in TOOLS
}


def tool_specs() -> list[dict]:
    """The MCP-facing tool specs (name/description/input_schema), no handlers."""
    from app.mcp import presets_tools  # Wave P PM3.0 (MH9): listed only while MCP_PRESETS_LIVE (MG4)

    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in TOOLS
    ] + presets_tools.specs()


def dispatch(session: Session, user_id: str, name: str, args: dict | None = None) -> dict:
    """Run tool ``name`` for ``user_id``. Raises :class:`MCPToolError` on failure."""
    from app.mcp import presets_tools

    if name in presets_tools.NAMES:
        return presets_tools.dispatch(session, user_id, name, args)
    handler = _BY_NAME.get(name)
    if handler is None:
        raise MCPToolError(f"unknown tool: {name}")
    return handler(session, user_id, args or {})
