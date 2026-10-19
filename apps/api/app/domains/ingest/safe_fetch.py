"""SSRF-safe fetchers for URL ingestion.

Both seams reuse :func:`app.domains.adstudio.fetch.safe_get` (http/https only,
no credentials, DNS resolved once and pinned, private/loopback/link-local
addresses refused, redirects followed manually with every hop re-validated,
body streamed under a byte cap, env proxies ignored).

* :func:`fetch_website` -- any public website (the ``website`` / store path).
* :func:`social_http_get` -- the social resolvers' HTTP seam. On top of the
  guard above, EVERY hop (the first URL and each redirect target) must be a
  known social-platform host, so a post link cannot bounce us anywhere else.

Failures surface as :class:`IngestError` with a user-presentable message.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

from app.domains.adstudio import fetch as _fetch
from app.domains.ingest.classify import platform_for_host
from app.domains.ingest.errors import IngestError

HttpGet = Callable[[str], "tuple[int, str]"]

SOCIAL_TIMEOUT_S = (8.0, 8.0)
WEBSITE_TIMEOUT_S = (8.0, 15.0)
SOCIAL_MAX_BYTES = 1_500_000
WEBSITE_MAX_BYTES = 2_000_000
_ACCEPT_LANGUAGE = "en-US,en;q=0.9"
_NOT_PUBLIC = "That link does not point to a public website"
_WEBSITE_MESSAGES = {
    404: "That page was not found",
    413: "That page is too large to read",
    422: _NOT_PUBLIC,
    424: "That site blocked our preview. Paste the details in manually instead",
}


# Public oEmbed / short-link hops that are not themselves "platform" hosts.
_EXTRA_SOCIAL_HOSTS = frozenset({"publish.twitter.com", "api.pinterest.com"})


def is_social_host(host: str | None) -> bool:
    host = (host or "").lower().rstrip(".")
    return host in _EXTRA_SOCIAL_HOSTS or platform_for_host(host) is not None


def _require_social_host(url: str) -> None:
    if not is_social_host(urlparse(url).hostname):
        raise _fetch.FetchError(422, "That link redirected somewhere we do not fetch")


class _AllowlistSession:
    """Session proxy that refuses to GET any non-social host (checked per hop)."""

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._inner, name, value)

    def get(self, url: str, **kwargs: Any) -> Any:
        _require_social_host(url)
        return self._inner.get(url, **kwargs)


def _default_session() -> Any:
    from app.services import webhooks

    if webhooks.requests is None:  # pragma: no cover - requests is a hard dep
        raise _fetch.FetchError(503, "URL fetching is unavailable on this server")
    return webhooks.requests.Session()


def social_http_get(
    url: str, *, session_factory: Callable[[], Any] | None = None
) -> tuple[int, str]:
    """GET a social-platform URL; returns ``(status, text)``.

    404 and "blocked" answers (401/403/429/503) come back as ``(404|403, "")``
    so resolvers can phrase a platform-specific message; everything else that
    fails raises :class:`IngestError`.
    """
    try:
        _fetch.normalize_public_url(url)
        _require_social_host(url)
        inner = session_factory or _default_session
        result = _fetch.safe_get(
            url,
            max_bytes=SOCIAL_MAX_BYTES,
            session_factory=lambda: _AllowlistSession(inner()),
            accept_language=_ACCEPT_LANGUAGE,
            timeout=SOCIAL_TIMEOUT_S,
        )
    except _fetch.FetchError as exc:
        if exc.status_code == 404:
            return 404, ""
        if exc.status_code == 424:
            return 403, ""
        raise IngestError(exc.status_code, _WEBSITE_MESSAGES.get(exc.status_code, exc.message)) from exc
    return result.status, result.text()


def fetch_website(url: str, *, session_factory: Callable[[], Any] | None = None) -> str:
    """SSRF-safe GET of any public page; returns its text or raises IngestError."""
    try:
        result = _fetch.safe_get(
            url,
            max_bytes=WEBSITE_MAX_BYTES,
            session_factory=session_factory,
            accept_language=_ACCEPT_LANGUAGE,
            timeout=WEBSITE_TIMEOUT_S,
        )
    except _fetch.FetchError as exc:
        message = _WEBSITE_MESSAGES.get(exc.status_code, exc.message)
        raise IngestError(exc.status_code, message) from exc
    return result.text()


__all__ = ["HttpGet", "fetch_website", "is_social_host", "social_http_get"]
