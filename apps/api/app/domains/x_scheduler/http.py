"""Small HTTPS helper for Buffer and Typefully. No extra dependency.

``transport`` is ``(method, url, headers, body) -> (status, body)`` so tests
can mock HTTP without a socket. Bodies are bytes. Timeouts fail as
:class:`ProviderHTTPError` rather than crashing the request.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from app.domains.x_scheduler.errors import redact

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]

_TIMEOUT_S = 30


class ProviderHTTPError(Exception):
    def __init__(self, status: int, message: str, payload: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.payload = payload


def default_transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310 - fixed provider hosts
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp is not None else b""
        return int(exc.code), raw
    except urllib.error.URLError as exc:
        raise ProviderHTTPError(502, "Could not reach the scheduling provider.") from exc


def request_json(
    transport: Transport,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict | None,
    *,
    secret: str,
    ok: tuple[int, ...] = (200,),
) -> Any:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    sent = dict(headers)
    if payload is not None:
        sent.setdefault("Content-Type", "application/json")
    try:
        status, raw = transport(method, url, sent, payload)
    except ProviderHTTPError:
        raise
    except Exception as exc:  # noqa: BLE001 - transport bugs become a provider error
        raise ProviderHTTPError(502, redact(f"Could not reach the scheduling provider: {exc}", secret)) from exc
    text = raw.decode("utf-8", errors="replace") if raw else ""
    parsed: Any = None
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
    if status not in ok:
        message = _message(parsed) or f"The scheduling provider returned HTTP {status}."
        raise ProviderHTTPError(status, redact(message, secret), parsed)
    return parsed


def put_bytes(transport: Transport, url: str, data: bytes, *, secret: str) -> None:
    """PUT raw bytes with no extra headers (Typefully's presigned upload)."""
    try:
        status, raw = transport("PUT", url, {}, data)
    except ProviderHTTPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProviderHTTPError(502, redact(f"Could not upload media: {exc}", secret)) from exc
    if status not in (200, 204):
        raise ProviderHTTPError(status, redact(f"Media upload failed (HTTP {status}).", secret), raw)


def _message(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    err = payload.get("error")
    if isinstance(err, dict) and err.get("message"):
        return str(err["message"])
    if isinstance(payload.get("message"), str):
        return str(payload["message"])
    return ""
