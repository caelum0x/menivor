"""Competitor backlink lookup: "where is this competitor listed/linked, so we
submit there too" (distribution playbook step 6).

Real backlink data (who links to a domain) is not public/keyless the way
Reddit search or the iTunes Search API are -- there are two practical
sources:

* **CrawlGraph** (crawlgraph.com) -- a free-tier (15 calls/month), Common
  Crawl-backed domain-level backlink API. No card required; preferred when
  configured since it costs nothing.
* **DataForSEO** -- the paid, URL-level provider OpenSEO already integrates
  (see ``~/products/gtm/openseo-selfhost-needs-dataforseo-2026-10-13.md`` in
  the owner's notes). Used as a fallback when CrawlGraph isn't configured.

So this module:

* always reports whether a usable key is configured (never guesses);
* never calls either paid/metered API unless a key is configured AND the
  caller explicitly passes ``allow_live=True`` -- callers never do that by
  default, so this never spends credits/quota on its own;
* when not configured/not live, returns an honest "not connected" result
  plus the owner step, and a same-category fallback: the launch directories
  from :mod:`app.domains.launch_kit.catalog` that fit general/SaaS products
  (a reasonable "submit here too" list without needing either paid API).
"""

from __future__ import annotations

import os
from typing import Any

from app.domains.launch_kit import catalog

DATAFORSEO_LOGIN_ENV = "DATAFORSEO_LOGIN"
DATAFORSEO_PASSWORD_ENV = "DATAFORSEO_PASSWORD"
CRAWLGRAPH_API_KEY_ENV = "CRAWLGRAPH_API_KEY"
LIVE_BACKLINKS_BASE = "https://api.dataforseo.com/v3/backlinks/backlinks/live"
CRAWLGRAPH_BACKLINKS_BASE = "https://crawlgraph.com/api/v1/backlinks"
SETUP_STEP = ("Competitor backlink data needs either a free CrawlGraph API key (crawlgraph.com, "
              "15 calls/month, no card) or a DataForSEO account (the same provider OpenSEO uses): "
              "the owner sets CRAWLGRAPH_API_KEY, or DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD. Until "
              "then this tool returns a free fallback list of general launch directories instead of "
              "live backlink data.")


class BacklinkError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _dataforseo_configured(source: dict[str, str]) -> bool:
    return bool(str(source.get(DATAFORSEO_LOGIN_ENV) or "").strip()) and bool(
        str(source.get(DATAFORSEO_PASSWORD_ENV) or "").strip())


def _crawlgraph_configured(source: dict[str, str]) -> bool:
    return bool(str(source.get(CRAWLGRAPH_API_KEY_ENV) or "").strip())


def configured(env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return _crawlgraph_configured(source) or _dataforseo_configured(source)


def _fallback(domain: str, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    source = os.environ if env is None else env
    directories = catalog.platforms_for_category(None)
    is_configured = _crawlgraph_configured(source) or _dataforseo_configured(source)
    return {
        "domain": domain, "live": False, "configured": is_configured, "backlinks": [],
        "fallback_directories": [{"id": p["id"], "name": p["name"], "url": p["url"]} for p in directories],
        "message": SETUP_STEP if not is_configured else
        "A key is configured but allow_live was not set, so no credits/quota were spent. Pass allow_live=true to fetch real backlinks.",
    }


def _fetch_crawlgraph(domain: str, *, transport: Any, api_key: str) -> dict[str, Any]:
    try:
        resp = transport.request(
            "POST", CRAWLGRAPH_BACKLINKS_BASE,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"domain": domain},
        )
    except Exception as exc:  # noqa: BLE001 - network boundary
        raise BacklinkError(f"CrawlGraph is unreachable ({type(exc).__name__}).", 502) from exc
    status = getattr(resp, "status_code", 200)
    if status >= 400:
        raise BacklinkError(f"CrawlGraph backlinks error {status}.", 502)
    try:
        body = resp.json() or {}
    except ValueError:
        body = {}
    rows = [{"source_domain": str(item.get("linking_domain") or ""), "target_url": "", "anchor": "",
             "rank": item.get("cg_rank"), "linking_hosts": item.get("num_hosts")}
            for item in (body.get("results") or [])]
    return {"domain": domain, "live": True, "configured": True, "backlinks": rows, "fallback_directories": [],
            "provider": "crawlgraph", "total_linking_domains": body.get("total_linking_domains"),
            "cg_authority": body.get("cg_authority"),
            "message": f"{len(rows)} live backlinking domain(s) from CrawlGraph (free tier, 15 calls/month)."}


def _fetch_dataforseo(domain: str, *, transport: Any, login: str, password: str) -> dict[str, Any]:
    import base64

    auth = base64.b64encode(f"{login}:{password}".encode()).decode()
    try:
        resp = transport.request(
            "POST", LIVE_BACKLINKS_BASE,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            json=[{"target": domain, "limit": 50, "mode": "as_is"}],
        )
    except Exception as exc:  # noqa: BLE001 - network boundary
        raise BacklinkError(f"DataForSEO is unreachable ({type(exc).__name__}).", 502) from exc
    status = getattr(resp, "status_code", 200)
    if status >= 400:
        raise BacklinkError(f"DataForSEO backlinks error {status}.", 502)
    try:
        body = resp.json() or {}
    except ValueError:
        body = {}
    items = (((body.get("tasks") or [{}])[0].get("result") or [{}])[0] or {}).get("items") or []
    rows = [{"source_domain": str(i.get("domain_from") or ""), "target_url": str(i.get("url_to") or ""),
             "anchor": str(i.get("anchor") or ""), "rank": i.get("rank")} for i in items]
    return {"domain": domain, "live": True, "configured": True, "backlinks": rows, "fallback_directories": [],
            "provider": "dataforseo", "message": f"{len(rows)} live backlink(s) from DataForSEO."}


def fetch(domain: str, *, transport: Any = None, allow_live: bool = False,
          env: dict[str, str] | None = None) -> dict[str, Any]:
    """Backlinks pointing at ``domain``. Returns the free fallback (never spends credits/quota)
    unless a key is configured AND ``allow_live`` is explicitly True. Prefers CrawlGraph (free)
    over DataForSEO (paid) when both are configured."""
    clean = str(domain or "").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    if not clean or "." not in clean:
        raise BacklinkError("domain must look like example.com", 422)
    source = os.environ if env is None else env
    if not allow_live:
        return _fallback(clean, env=env)
    crawlgraph_key = str(source.get(CRAWLGRAPH_API_KEY_ENV) or "").strip()
    if crawlgraph_key:
        return _fetch_crawlgraph(clean, transport=transport, api_key=crawlgraph_key)
    if _dataforseo_configured(source):
        login = str(source.get(DATAFORSEO_LOGIN_ENV) or "")
        password = str(source.get(DATAFORSEO_PASSWORD_ENV) or "")
        return _fetch_dataforseo(clean, transport=transport, login=login, password=password)
    return _fallback(clean, env=env)


__all__ = ["BacklinkError", "SETUP_STEP", "configured", "fetch"]
