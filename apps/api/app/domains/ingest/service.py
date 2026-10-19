"""URL -> reel service: classify any link, resolve it, assemble a reel draft.

* website / app_store / play_store: fetch the page (SSRF-safe), extract
  title/description/features, template a hook-first draft (unchanged shape).
* social_post: resolve the post via free public endpoints, keep its angle as
  ``inspiration`` and build "a reel inspired by this" for the user's product.
* social_profile: resolve the profile into ``brand`` facts plus a draft.

The website fetcher, social HTTP seam and optional LLM rewriter are injectable
so the flow is fully testable offline. Never persists -- the returned draft is
submitted by the client to ``POST /jobs``.
"""

from __future__ import annotations

from typing import Callable

from app.domains.ingest import safe_fetch
from app.domains.ingest.classify import (
    KIND_SOCIAL_POST,
    KIND_SOCIAL_PROFILE,
    UrlClassifyError,
    UrlKind,
    classify_url,
)
from app.domains.ingest.draft import build_reel_draft
from app.domains.ingest.errors import IngestError
from app.domains.ingest.extract import extract_content
from app.domains.ingest.inspired import build_inspired_draft
from app.domains.ingest.social import SocialResult, resolve_social

Fetcher = Callable[[str], str]
Rewriter = Callable[[dict, dict], dict]
HttpGet = safe_fetch.HttpGet

_MAX_FETCH_BYTES = 2_000_000


def _default_fetch(url: str) -> str:
    """SSRF-safe GET returning page text (raises IngestError on failure)."""
    return safe_fetch.fetch_website(url)[:_MAX_FETCH_BYTES]


def _default_http(url: str) -> tuple[int, str]:
    """Allowlisted SSRF-safe GET for social platforms."""
    return safe_fetch.social_http_get(url)


def detect(url: str) -> UrlKind:
    """Classify without any network access (raises IngestError 400 on junk)."""
    try:
        return classify_url(url)
    except UrlClassifyError as exc:
        raise IngestError(400, "a valid http(s) URL is required") from exc


def _source(kind: UrlKind, note: str | None = None) -> dict:
    return {
        "kind": kind.kind,
        "platform": kind.platform,
        "label": kind.label,
        "handle": kind.handle,
        "note": note,
    }


def _polish(draft: dict, content: dict, rewriter: Rewriter | None) -> dict:
    if rewriter is None:
        return draft
    try:
        return {**draft, **(rewriter(draft, content) or {})}
    except Exception:  # noqa: BLE001 - rewrite is best-effort polish
        return draft


class IngestService:
    def url_to_reel(
        self,
        url: str,
        *,
        fetcher: Fetcher | None = None,
        rewriter: Rewriter | None = None,
        http: HttpGet | None = None,
    ) -> dict:
        """Classify ``url`` and return ``{url, source, content, reel_draft, ...}``."""
        kind = detect(url)
        if kind.kind in (KIND_SOCIAL_POST, KIND_SOCIAL_PROFILE):
            return self._social(kind, http or _default_http, rewriter)
        return self._website(kind, fetcher or _default_fetch, rewriter)

    def _website(self, kind: UrlKind, fetch: Fetcher, rewriter: Rewriter | None) -> dict:
        content = extract_content(fetch(kind.url), kind.url)
        if not content.get("title") and not content.get("description"):
            raise IngestError(422, "could not extract usable content from the page")
        draft = _polish(build_reel_draft(content), content, rewriter)
        return {"url": kind.url, "source": _source(kind), "content": content, "reel_draft": draft}

    def _social(self, kind: UrlKind, http: HttpGet, rewriter: Rewriter | None) -> dict:
        result: SocialResult = resolve_social(kind, http)
        out = {"url": kind.url, "source": _source(kind, result.note), "content": result.content}
        if result.inspiration is not None:
            draft = build_inspired_draft(result.inspiration, kind.platform)
            out["inspiration"] = result.inspiration
        else:
            draft = build_reel_draft(result.content)
            out["brand"] = result.brand
        out["reel_draft"] = _polish(draft, result.content, rewriter)
        return out


__all__ = ["IngestError", "IngestService", "detect"]
