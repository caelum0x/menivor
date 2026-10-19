"""Generate the production API allowlist from what the clients actually call (M3.3).

Reads every FastAPI route the API mounts (``app.router.build_full_router()``)
and searches the client trees for a literal that names it:

* ``web``     - ``apps/web/{app,lib,components,src,features}``
* ``mobile``  - ``apps/mobile/{app,src,lib,components,hooks}``
* ``desktop`` - ``apps/desktop/src``
* ``mcp``     - ``apps/web/lib/mcp`` and ``apps/api/app/mcp`` (the stdio MCP
  server calls domain code directly, so it adds no HTTP routes; its tool list is
  recorded in the audit for completeness)
* ``contract`` - routes the product contract makes public before a client
  screen names them (``CONTRACT_ROUTES``: quote, preset quote, keep).
* ``server``  - routes called by third parties, not by our clients (payment and
  identity webhooks, OAuth callbacks, the Prometheus scrape, the developer API).
  These are listed by prefix in ``SERVER_PREFIXES`` with the caller named.

A client literal matches a route when both normalise to the same template:
``${expr}`` and ``{name}`` become ``{}``, the ``/api/v1`` prefix and any query
string are dropped. The output is:

* ``apps/api/app/core/api_surface_allowlist.json`` - the ``METHOD path`` list
  the router mounts publicly under ``MENIVOR_API_SURFACE=allowlist``;
* ``docs/api/ROUTE-AUDIT.md`` - every kept route mapped to its client and file.

Run from the repo root:  ``PYTHONPATH=apps/api python apps/api/tools/ops/api_surface_audit.py``
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
#: Client source root (default: this repo). Set to an exported tree to audit another revision.
CLIENT_ROOT = Path(os.environ.get("API_SURFACE_CLIENT_ROOT") or REPO)
API = REPO / "apps" / "api"
ALLOWLIST_JSON = API / "app" / "core" / "api_surface_allowlist.json"
AUDIT_MD = REPO / "docs" / "api" / "ROUTE-AUDIT.md"

CLIENT_TREES: dict[str, tuple[str, ...]] = {
    # The web app also calls paths kept in the shared contract package (e.g. WALLET_PATHS).
    "web": ("apps/web/app", "apps/web/lib", "apps/web/components", "apps/web/src", "apps/web/features",
            "packages/api-contract/src"),
    "mobile": ("apps/mobile/app", "apps/mobile/src", "apps/mobile/lib", "apps/mobile/components",
               "apps/mobile/hooks"),
    "desktop": ("apps/desktop/src",),
    # Wave P PM3.3 (MV8, MV9): the Menivor TV viewer app (phones and TVs).
    "watch": ("apps/watch/app", "apps/watch/src"),
}
SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".rs", ".mdx", ".md")
#: Test files name example paths; only shipped client code decides what is reachable.
_TEST_FILE = re.compile(r"\.(test|spec)\.[a-z]+$")
SKIP_DIRS = {"node_modules", ".next", "dist", "build", "target", "__tests__", "e2e"}

# Third-party callers: routes that no first-party client calls but that must
# stay public. Prefixes are matched against the normalised path.
SERVER_PREFIXES: dict[str, str] = {
    "/webhooks/": "payment, identity and platform webhooks (Dodo, Clerk, social platforms)",
    "/multipost/webhooks/": "TikTok Content Posting status webhook (signed, Autopost)",
    "/integrations/slack/": "Slack slash command, Events API and button clicks (Slack-signed, Ads agent)",
    "/billing/webhook": "Dodo payment webhook",
    "/wallet/webhook": "wallet top-up webhook",
    "/oauth/": "social platform OAuth callbacks",
    "/connections/{}/callback": "social platform OAuth callbacks",
    "/metrics": "Prometheus scrape on box 2 (observability plane)",
    "/mcp": "hosted MCP connector for AI agents (bearer connector token; spending tools only queue approvals)",
    "/media/": "developer media gateway (API customers with a key; /docs page)",
    "/v1/": "OpenAI-shaped developer gateway (API customers with a key)",
    "/ott/nodes/": "OTT transcode nodes: the owner's Mac and burst boxes (bearer node token; 404 until OTT_PACKAGING_LIVE)",
    "/ott/stream/": "OTT players following tokenized manifest and segment URLs (404 until OTT_STOREFRONT_LIVE)",
    "/ott/keys/": "OTT players fetching the tier-1 key named in a playlist (valid token only; OTT_ACCESS_LIVE)",
    "/ott/feeds/": "feed readers and podcast apps following feed item links (404 until OTT_FEEDS_LIVE)",
    "/ott/c/{}/rss.xml": "RSS readers (404 until OTT_FEEDS_LIVE)",
    "/ott/c/{}/mrss.xml": "MRSS partners (404 until OTT_FEEDS_LIVE)",
    "/ott/c/{}/podcast.xml": "podcast apps (404 until OTT_FEEDS_LIVE)",
    "/ott/oembed": "oEmbed consumers (404 until OTT_EMBED_LIVE)",
    "/ott/webhooks/": "Mint seller-own entitlement events, Standard Webhooks signed (404 until OTT_COMMERCE_LIVE)",
    "/ott/ads/track/": "players firing VAST tracking URLs, signed per event (404 until OTT_ADS_LIVE)",
    "/ott/live/hooks/": "the MediaMTX live server: auth, ready, ended and recording hooks (shared secret; OTT_LIVE_LIVE)",
    "/ott/linear/{}/items/": "the FAST playout engine asking for the next item (engine key; OTT_FAST_LIVE)",
    "/ott/linear/{}/epg.xml": "XMLTV guide readers and FAST distribution partners (404 until OTT_FAST_LIVE)",
    "/ott/beacons": "OTT players sending first-party quality beacons (404 until OTT_ANALYTICS_LIVE)",
}

# Product-contract routes: public by design even before a first-party screen
# names them literally (Wave D hand-off H1). "A price before every render"
# (MG3, MH1) and charge on keep (M3.1) break for users if these answer 404.
# Matched against the normalised path; the caller is recorded in the audit.
CONTRACT_ROUTES: dict[str, str] = {
    "/jobs/quote": "create flow price before render (MG3; web, mobile, MCP)",
    "/jobs/quote/preset": "AI-video preset price before render (MH1)",
    "/jobs/{}/keep": "keep a variant, charge on keep (M3.1)",
}

_PARAM = re.compile(r"\{[^}/]*\}")
#: Where a path literal can start: a quote or backtick followed by "/", or a backtick
#: followed by one leading interpolation and "/" (``${API_BASE}/jobs``).
_START = re.compile(r"[\"']/|`(?:\$\{[^`]*?\})?/")
_LINE_COMMENT = re.compile(r"(?:^|[^:\"'`])//")  # "//" outside a URL scheme
_SENT = "\x00"  # one interpolated value, before it is turned into a path segment


def _skip_string(text: str, i: int) -> int:
    """``text[i]`` is a quote; return the index after the closing quote (same line)."""
    quote, i = text[i], i + 1
    while i < len(text) and text[i] not in (quote, "\n"):
        i += 2 if text[i] == "\\" else 1
    return i + 1


def _skip_expr(text: str, i: int) -> int:
    """``i`` is just after ``${``; return the index after the matching ``}`` (nested calls,
    objects, strings and templates included)."""
    depth = 0
    while i < len(text):
        c = text[i]
        if c in "'\"":
            i = _skip_string(text, i)
            continue
        if c == "`":
            i = _template(text, i + 1)[1]
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            if depth == 0:
                return i + 1
            depth -= 1
        i += 1
    return i


def _template(text: str, i: int) -> tuple[str, int]:
    """``i`` is just after an opening backtick; return (content with each ``${...}`` as one
    sentinel, index after the closing backtick)."""
    out: list[str] = []
    while i < len(text):
        c = text[i]
        if c == "\\":
            out.append(text[i:i + 2])
            i += 2
        elif c == "`":
            return "".join(out), i + 1
        elif text.startswith("${", i):
            i = _skip_expr(text, i + 2)
            out.append(_SENT)
        else:
            out.append(c)
            i += 1
    return "".join(out), i


def path_literals(text: str):
    """Every string or template literal in ``text`` that is an absolute path, with each
    interpolation (``${encodeURIComponent(id)}``, ``${a ?? b}``, nested templates ...) as a
    sentinel. A leading interpolation (an API base URL) is dropped."""
    for m in _START.finditer(text):
        start = m.start()
        line = text[text.rfind("\n", 0, start) + 1:start].lstrip()
        if line.startswith(("*", "/*", "#")) or _LINE_COMMENT.search(line):
            continue  # a path named in a comment or doc block is not a call
        if text[start] == "`":
            raw = _template(text, start + 1)[0]
            if raw.startswith(_SENT):
                raw = raw[1:]
        else:
            end = _skip_string(text, start)
            raw = text[start + 1:end - 1]
        if raw.startswith("/"):
            yield raw


def normalise(path: str) -> str:
    """Client literal or route path -> one template: every parameter or interpolated value is
    ``{}``, the ``/api/v1`` prefix and the query string are dropped. An interpolation glued to
    the end of the last segment (``/ads${query}``) is a query suffix and is dropped too."""
    p = path
    if "${" in p:
        p, i, out = p, 0, []
        while i < len(p):
            if p.startswith("${", i):
                i = _skip_expr(p, i + 2)
                out.append(_SENT)
            else:
                out.append(p[i])
                i += 1
        p = "".join(out)
    p = p.split("?", 1)[0].split("#", 1)[0]
    p = _PARAM.sub(_SENT, p)
    if p.startswith("/api/v1"):
        p = p[len("/api/v1"):] or "/"
    segments = [s for s in p.split("/") if s]
    out_segments = []
    for n, seg in enumerate(segments):
        if _SENT not in seg:
            out_segments.append(seg)
        elif n == len(segments) - 1 and not seg.startswith(_SENT):
            out_segments.append(seg.split(_SENT, 1)[0])
        else:
            out_segments.append("{}")
    return "/" + "/".join(out_segments)


def iter_sources(trees: tuple[str, ...]):
    for rel in trees:
        root = CLIENT_ROOT / rel
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f.suffix in SOURCE_SUFFIXES and not (SKIP_DIRS & set(f.parts)) \
                    and not _TEST_FILE.search(f.name):
                yield f


def client_literals() -> dict[str, dict[str, str]]:
    """``{normalised path: {client: first file}}`` for every path literal in the clients."""
    found: dict[str, dict[str, str]] = {}
    for client, trees in CLIENT_TREES.items():
        for f in iter_sources(trees):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for raw in path_literals(text):
                norm = normalise(raw)
                if norm == "/":
                    continue
                found.setdefault(norm, {}).setdefault(client, str(f.relative_to(CLIENT_ROOT)))
    return found


def server_caller(norm: str) -> str | None:
    if norm in CONTRACT_ROUTES:
        return CONTRACT_ROUTES[norm]
    for prefix, who in SERVER_PREFIXES.items():
        if norm == prefix.rstrip("/") or norm.startswith(prefix if prefix.endswith("/") else prefix):
            return who
    return None


def audit(routes: list[tuple[str, str]]) -> tuple[list[dict], list[dict]]:
    literals = client_literals()
    kept, hidden = [], []
    for method, path in routes:
        norm = normalise(path)
        clients = literals.get(norm, {})
        row = {"method": method, "path": path, "clients": clients}
        who = server_caller(norm)
        if clients:
            kept.append(row)
        elif who:
            kept.append({**row, "clients": {"server": who}})
        else:
            hidden.append(row)
    return kept, hidden


def mounted_routes() -> list[tuple[str, str]]:
    sys.path.insert(0, str(API))
    sys.path.insert(0, str(REPO))
    from tests.reelforge._session_env import apply_hermetic_env

    apply_hermetic_env()
    from fastapi.routing import APIRoute

    from app.router import build_full_router

    out = []
    for r in build_full_router().routes:
        if isinstance(r, APIRoute):
            for m in sorted(r.methods or ()):
                if m not in ("HEAD", "OPTIONS"):
                    out.append((m, r.path))
    return sorted(set(out), key=lambda x: (x[1], x[0]))


def mcp_tools() -> list[str]:
    from app.mcp.tools import tool_specs

    return [t["name"] for t in tool_specs()]


def write(kept: list[dict], hidden: list[dict], frozen: list[tuple[str, str]], tools: list[str]) -> None:
    allow = sorted({f"{r['method']} {r['path']}" for r in kept})
    ALLOWLIST_JSON.write_text(json.dumps({
        "generated_by": "apps/api/tools/ops/api_surface_audit.py",
        "routes": allow,
    }, indent=2) + "\n", encoding="utf-8")

    paths_kept = sorted({r["path"] for r in kept})
    lines = [
        "# Production API route audit (M3.3)",
        "",
        "Generated by `apps/api/tools/ops/api_surface_audit.py`; do not edit by hand.",
        "Re-run it after a client starts calling a new route, then commit both this",
        "file and `apps/api/app/core/api_surface_allowlist.json`.",
        "",
        "Under `MENIVOR_API_SURFACE=allowlist` (the default when",
        "`REELFORGE_LAUNCH_MODE=public`) only the routes below are public. Every",
        "other route stays mounted for staff only (404 for everyone else, hidden",
        "from OpenAPI). Frozen money routes are not mounted at all. Nothing is",
        "deleted from the tree; `MENIVOR_API_SURFACE=full` restores the full surface.",
        "",
        f"- Public routes: {len(allow)} method+path pairs on {len(paths_kept)} paths.",
        f"- Staff-only routes: {len(hidden)}.",
        f"- Frozen (not mounted): {len(frozen)}.",
        f"- MCP (stdio) tools, which call domain code directly: {', '.join(tools)}.",
        "",
        "## Public routes and their clients",
        "",
        "| Method | Path | Client | Where |",
        "|---|---|---|---|",
    ]
    for r in sorted(kept, key=lambda r: (r["path"], r["method"])):
        for client, where in sorted(r["clients"].items()):
            lines.append(f"| {r['method']} | `{r['path']}` | {client} | {where} |")
    lines += ["", "## Frozen money routes (not mounted under the allowlist)", "",
              "| Method | Path |", "|---|---|"]
    lines += [f"| {m} | `{p}` |" for m, p in frozen]
    lines += ["", "## Staff-only routes", "", "| Method | Path |", "|---|---|"]
    lines += [f"| {r['method']} | `{r['path']}` |" for r in hidden]
    AUDIT_MD.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    from app.core.api_surface import is_frozen, is_staff_only

    routes = mounted_routes()
    frozen = [(m, p) for m, p in routes if is_frozen(p)]
    live = [(m, p) for m, p in routes if not is_frozen(p) and not is_staff_only(p)]
    kept, hidden = audit(live)
    hidden += [{"method": m, "path": p, "clients": {}} for m, p in routes if is_staff_only(p)]
    write(kept, hidden, frozen, mcp_tools())
    paths = {r["path"] for r in kept}
    print(f"public: {len(kept)} routes on {len(paths)} paths; staff-only: {len(hidden)}; frozen: {len(frozen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
