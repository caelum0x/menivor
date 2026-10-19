"""SSRF-guarded HTTP GET for Ad Studio product pages and product images.

Every hop (the initial URL and each redirect target) is:

* syntax-checked (http/https only, no credentials, bounded length, no control
  characters);
* resolved ONCE and rejected when any resolved address is loopback / private /
  link-local / reserved / multicast (the shared webhook SSRF classifier), with
  the operator's webhook "allow internal" override deliberately ignored because
  this URL is user-authored;
* connected through the DNS-pinned adapter so the socket lands on exactly the
  vetted IP (closes the DNS-rebinding window);
* fetched with environment proxies disabled and redirects handled manually.

The body is streamed with a hard byte cap so a hostile server cannot exhaust
memory.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urljoin, urlparse, urlunparse

MAX_URL_LENGTH = 2048
MAX_REDIRECTS = 4
CONNECT_TIMEOUT_S = 8
READ_TIMEOUT_S = 20
PAGE_MAX_BYTES = 4_000_000
IMAGE_MAX_BYTES = 12_000_000

# Marketplaces serve a stripped or bot-wall page to obvious crawler agents, so
# the fetcher identifies as a mainstream desktop browser while still being a
# single polite GET per product page.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "instance-data.ec2.internal",
    }
)


class FetchError(Exception):
    """A user-presentable fetch failure carrying an HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    content_type: str
    body: bytes

    def text(self) -> str:
        charset = "utf-8"
        for part in self.content_type.split(";")[1:]:
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset" and value:
                charset = value.strip().strip('"')
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def normalize_public_url(raw_url: str) -> str:
    """Return a canonical http(s) URL or raise :class:`FetchError` (422)."""
    url = (raw_url or "").strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise FetchError(422, "a valid http(s) product URL is required")
    if any(ord(ch) < 32 or ch.isspace() or ch == "\\" for ch in url):
        raise FetchError(422, "the URL contains invalid characters")
    try:
        parsed = urlparse(url)
        _ = parsed.port
    except (TypeError, ValueError) as exc:
        raise FetchError(422, "the URL is not valid") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise FetchError(422, "only http(s) URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise FetchError(422, "URLs with embedded credentials are not allowed")
    host = parsed.hostname.strip().lower().rstrip(".")
    if host in _BLOCKED_HOSTS or host.endswith(".internal") or host.endswith(".local"):
        raise FetchError(422, "the URL does not point to a public website")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise FetchError(422, "the URL does not point to a public website")
    return urlunparse(parsed._replace(scheme=scheme, fragment=""))


def _pinned_ip(url: str) -> str:
    from app.services import webhooks

    error, pinned = webhooks._validate_and_resolve(url)
    if error is not None or not pinned or webhooks._ip_is_internal(pinned):
        raise FetchError(422, "the URL does not point to a public website")
    return pinned


def _read_capped(response: Any, max_bytes: int) -> bytes:
    announced = str(response.headers.get("Content-Length", "") or "").strip()
    if announced.isdigit() and int(announced) > max_bytes:
        raise FetchError(413, "the remote resource is too large")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(413, "the remote resource is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def safe_get(
    raw_url: str,
    *,
    max_bytes: int = PAGE_MAX_BYTES,
    accept: str = "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5",
    session_factory: Callable[[], Any] | None = None,
    accept_language: str = "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    timeout: tuple[float, float] = (CONNECT_TIMEOUT_S, READ_TIMEOUT_S),
) -> FetchResult:
    """GET a public URL with the full SSRF guard; returns the capped body."""
    from app.services import webhooks

    requests = webhooks.requests
    adapter_cls = webhooks._PinnedHTTPAdapter
    if requests is None or adapter_cls is None:
        raise FetchError(503, "URL fetching is unavailable on this server")
    make_session = session_factory or requests.Session

    current = normalize_public_url(raw_url)
    seen = {current}
    for hop in range(MAX_REDIRECTS + 1):
        pinned = _pinned_ip(current)
        session = make_session()
        response = None
        try:
            if hasattr(session, "trust_env"):
                session.trust_env = False
            adapter = adapter_cls(pinned)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            try:
                response = session.get(
                    current,
                    stream=True,
                    timeout=timeout,
                    allow_redirects=False,
                    headers={
                        "User-Agent": BROWSER_USER_AGENT,
                        "Accept": accept,
                        "Accept-Language": accept_language,
                    },
                )
            except FetchError:
                raise
            except Exception as exc:  # noqa: BLE001 - normalize transport errors
                raise FetchError(502, "could not reach the URL") from exc
            status = int(response.status_code)
            if status in _REDIRECT_STATUSES:
                location = str(response.headers.get("Location", "") or "").strip()
                if not location or hop >= MAX_REDIRECTS:
                    raise FetchError(502, "the URL redirected too many times")
                target = normalize_public_url(urljoin(current, location))
                if target in seen:
                    raise FetchError(502, "the URL redirect loops")
                seen.add(target)
                current = target
                continue
            if status == 404:
                raise FetchError(404, "the product page was not found (404)")
            if status in {401, 403, 429, 503}:
                raise FetchError(
                    424,
                    "the store blocked the automated page fetch "
                    f"(HTTP {status}); enter the product details manually instead",
                )
            if status >= 400:
                raise FetchError(502, f"the URL returned HTTP {status}")
            body = _read_capped(response, max_bytes)
            content_type = str(response.headers.get("Content-Type", "") or "")
            return FetchResult(current, status, content_type, body)
        finally:
            if response is not None:
                response.close()
            session.close()
    raise FetchError(502, "the URL redirected too many times")


__all__ = [
    "BROWSER_USER_AGENT",
    "FetchError",
    "FetchResult",
    "IMAGE_MAX_BYTES",
    "PAGE_MAX_BYTES",
    "normalize_public_url",
    "safe_get",
]
