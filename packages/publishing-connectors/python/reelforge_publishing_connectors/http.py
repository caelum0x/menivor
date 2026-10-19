"""Dependency-free HTTP+JSON transport for the platform clients (mirror of ``src/http.ts``).

Timeout + bounded retry (only transient 429 / 5xx) + JSON, built on the stdlib
``urllib`` so the SDK keeps **zero runtime dependencies** (matching the TS port's
dependency-free ``fetch`` wrapper). No token storage — the caller passes the
bearer token in per request (the stateless security seam).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

# Sentinel distinguishing "no body" (undefined in TS) from an explicit ``None`` body.
_UNSET: Any = object()


@dataclass(frozen=True)
class HttpOptions:
    """Per-call request options (immutable). Mirrors the TS ``HttpOptions``."""

    method: str = "GET"
    headers: dict[str, str] | None = None
    body: Any = _UNSET
    token: str | None = None  # bearer token injected per call (never persisted)
    timeout_ms: int = 30_000
    retries: int = 2


class HttpError(Exception):
    """A non-retryable (or retries-exhausted) HTTP failure, mirror of TS ``HttpError``."""

    def __init__(self, status: int, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


# The injectable transport signature the clients depend on: ``(url, options) -> parsed``.
HttpFn = Callable[..., Any]


def http_json(url: str, options: HttpOptions | None = None) -> Any:
    """Perform one JSON request with bounded retry; returns the parsed body.

    Only transient ``429`` / ``5xx`` responses and transport errors are retried
    (capped exponential backoff), identical to the TS wrapper.
    """
    opts = options or HttpOptions()
    method = (opts.method or "GET").upper()
    retries = max(0, int(opts.retries))
    timeout_s = max(0.0, opts.timeout_ms / 1000)
    has_body = opts.body is not _UNSET

    headers: dict[str, str] = {"Accept": "application/json", **(opts.headers or {})}
    if opts.token:
        headers["Authorization"] = f"Bearer {opts.token}"
    if has_body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    data = json.dumps(opts.body).encode("utf-8") if has_body else None

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                text = resp.read().decode("utf-8")
                return _safe_parse(text) if text else None
        except urllib.error.HTTPError as err:
            text = err.read().decode("utf-8", "replace")
            body = _safe_parse(text) if text else None
            if (err.code == 429 or err.code >= 500) and attempt < retries:
                last_err = HttpError(err.code, f"HTTP {err.code}", body)
                time.sleep(_backoff_s(attempt))
                continue
            raise HttpError(err.code, f"HTTP {err.code}", body if body is not None else text)
        except (urllib.error.URLError, TimeoutError) as err:
            last_err = err
            if attempt < retries:
                time.sleep(_backoff_s(attempt))
                continue

    if isinstance(last_err, Exception):
        raise last_err
    raise RuntimeError("request failed")


def encode_uri_component(value: str) -> str:
    """Match JavaScript ``encodeURIComponent`` so query strings are byte-identical.

    ``encodeURIComponent`` leaves ``A-Z a-z 0-9 - _ . ! ~ * ' ( )`` unescaped and
    percent-encodes everything else (including ``/``).
    """
    return urllib.parse.quote(str(value), safe="!*'()")


def _safe_parse(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def _backoff_s(attempt: int) -> float:
    return min(8.0, (2 ** attempt) * 0.5)
