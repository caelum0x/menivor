"""Native-ComfyUI HTTP client + its injectable transport seam.

This is the ONLY thing in the local-ComfyUI path that touches the network. The
native ComfyUI API (unlike the comfyui-deploy remote path) needs a *multipart*
image upload and a *raw-bytes* GET (``/view``) that the JSON-only render
``base.Transport`` / routing ``build_json_transport`` seams cannot express, so
this module defines a purpose-built :class:`ComfyTransport` protocol with three
verbs — ``request_json`` / ``request_multipart`` / ``request_bytes`` — plus a
default :class:`RequestsComfyTransport` (lazy ``requests`` import).

Wrapped native endpoints:

* ``upload_image()``  — multipart ``POST /upload/image`` → ``{name, subfolder, type}``
* ``submit_prompt()`` — ``POST /prompt``  → ``{prompt_id, number, node_errors}``
  (raises :class:`BackendError` on HTTP 400 carrying ``node_errors``)
* ``get_history()``   — ``GET /history/{id}`` — an empty ``{}`` (queued/running or
  404) is treated as *still pending*, NEVER a failure
* ``view_url()``      — builds ``GET /view?filename=&subfolder=&type=``
* ``fetch_view()``    — ``GET /view`` raw bytes (optional download to storage)
* ``object_info()`` / ``interrupt()`` / ``clear_queued()`` — warm + cancel helpers

Every failure is normalized to :class:`BackendError` with ``retryable=True`` for
5xx / network errors and ``retryable=False`` for 4xx — a raw ``requests`` error
never escapes.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlencode

from app.services.render.backends.base import BackendError

_BACKEND = "local_comfyui"


# --------------------------------------------------------------------------- #
# Transport seam
# --------------------------------------------------------------------------- #
@runtime_checkable
class ComfyResponse(Protocol):
    """The minimal response shape the client reads (a ``requests.Response`` fits)."""

    status_code: int

    def json(self) -> Any: ...

    @property
    def content(self) -> bytes: ...


@runtime_checkable
class ComfyTransport(Protocol):
    """The single network seam for native ComfyUI (JSON + multipart + raw bytes)."""

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        json: Any | None = None,
    ) -> ComfyResponse: ...

    def request_multipart(
        self,
        url: str,
        *,
        files: dict,
        data: dict | None = None,
        headers: dict | None = None,
    ) -> ComfyResponse: ...

    def request_bytes(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
    ) -> ComfyResponse: ...


class RequestsComfyTransport:
    """Default :class:`ComfyTransport` backed by ``requests`` (lazy import)."""

    def __init__(self, timeout_s: float = 1800.0) -> None:
        self._timeout = timeout_s

    def request_json(self, method, url, *, headers=None, params=None, json=None):
        import requests

        return requests.request(
            method, url, headers=headers, params=params, json=json, timeout=self._timeout
        )

    def request_multipart(self, url, *, files, data=None, headers=None):
        import requests

        return requests.post(
            url, files=files, data=data, headers=headers, timeout=self._timeout
        )

    def request_bytes(self, method, url, *, headers=None, params=None):
        import requests

        return requests.request(
            method, url, headers=headers, params=params, timeout=self._timeout
        )


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
def _status(resp: Any) -> int:
    return int(getattr(resp, "status_code", 0) or 0)


def _ok(resp: Any) -> bool:
    return 200 <= _status(resp) < 300


def _safe_json(resp: Any) -> dict:
    try:
        body = resp.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {"data": body}


class ComfyUIClient:
    """A thin native-ComfyUI HTTP client bound to one base URL + transport."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: ComfyTransport | None = None,
        timeout_s: float = 1800.0,
    ) -> None:
        if not str(base_url or "").strip():
            raise BackendError(_BACKEND, "comfyui base_url is required")
        self._base = str(base_url).rstrip("/")
        self._transport: ComfyTransport = transport or RequestsComfyTransport(timeout_s)

    # -- low-level guarded calls ------------------------------------------- #
    def _json(self, method, path, *, params=None, json=None) -> Any:
        url = f"{self._base}{path}"
        try:
            return self._transport.request_json(method, url, params=params, json=json)
        except BackendError:
            raise
        except Exception as exc:  # network error -> retryable
            raise BackendError(_BACKEND, f"{method} {path} failed: {exc}", retryable=True) from exc

    def _check(self, resp: Any, action: str) -> None:
        if _ok(resp):
            return
        status = _status(resp)
        raise BackendError(
            _BACKEND, f"{action} failed (HTTP {status}): {_safe_json(resp)}",
            retryable=status >= 500 or status == 0,
        )

    # -- endpoints ---------------------------------------------------------- #
    def upload_image(
        self,
        filename: str,
        data: bytes,
        *,
        image_type: str = "input",
        subfolder: str = "",
        overwrite: bool = True,
    ) -> dict:
        """Multipart ``POST /upload/image`` → ``{name, subfolder, type}``."""
        files = {"image": (filename, data, "application/octet-stream")}
        form = {"type": image_type, "overwrite": "true" if overwrite else "false"}
        if subfolder:
            form["subfolder"] = subfolder
        try:
            resp = self._transport.request_multipart(
                f"{self._base}/upload/image", files=files, data=form
            )
        except Exception as exc:
            raise BackendError(_BACKEND, f"upload_image failed: {exc}", retryable=True) from exc
        self._check(resp, "upload_image")
        body = _safe_json(resp)
        return {
            "name": str(body.get("name") or filename),
            "subfolder": str(body.get("subfolder") or subfolder or ""),
            "type": str(body.get("type") or image_type),
        }

    def submit_prompt(self, graph: dict, client_id: str | None = None) -> dict:
        """``POST /prompt`` → ``{prompt_id, number, node_errors}``.

        A validation error (HTTP 400 with ``node_errors``) is a permanent
        :class:`BackendError` (not retryable) so the worker fails fast rather than
        replaying an illegal graph.
        """
        payload: dict[str, Any] = {"prompt": graph}
        if client_id:
            payload["client_id"] = client_id
        resp = self._json("POST", "/prompt", json=payload)
        status = _status(resp)
        if status == 400:
            body = _safe_json(resp)
            raise BackendError(
                _BACKEND,
                f"prompt validation failed: node_errors={body.get('node_errors', {})} "
                f"error={body.get('error', '')}",
                retryable=False,
            )
        self._check(resp, "submit_prompt")
        body = _safe_json(resp)
        if not body.get("prompt_id"):
            raise BackendError(_BACKEND, f"submit_prompt returned no prompt_id: {body}")
        return body

    def get_history(self, prompt_id: str) -> dict:
        """``GET /history/{id}`` → the entry for ``prompt_id`` (``{}`` while pending).

        ComfyUI returns ``{}`` (or 404) while a prompt is queued/running; this is
        NOT a failure — the caller keeps the job IN_PROGRESS. Once the prompt is
        recorded the body is ``{prompt_id: {status, outputs, ...}}`` and the inner
        entry is returned.
        """
        resp = self._json("GET", f"/history/{prompt_id}")
        status = _status(resp)
        if status == 404:
            return {}
        if status >= 500 or status == 0:
            raise BackendError(
                _BACKEND, f"get_history failed (HTTP {status})", retryable=True
            )
        if not _ok(resp):
            raise BackendError(
                _BACKEND, f"get_history failed (HTTP {status}): {_safe_json(resp)}",
                retryable=False,
            )
        body = _safe_json(resp)
        entry = body.get(str(prompt_id))
        return entry if isinstance(entry, dict) else {}

    def view_url(self, filename: str, subfolder: str = "", image_type: str = "output") -> str:
        """Build the ``GET /view`` URL for a saved output file."""
        query = urlencode(
            {"filename": filename, "subfolder": subfolder or "", "type": image_type or "output"}
        )
        return f"{self._base}/view?{query}"

    def fetch_view(self, filename: str, subfolder: str = "", image_type: str = "output") -> bytes:
        """``GET /view`` raw bytes (optional download to local storage)."""
        url = self.view_url(filename, subfolder, image_type)
        try:
            resp = self._transport.request_bytes("GET", url)
        except Exception as exc:
            raise BackendError(_BACKEND, f"fetch_view failed: {exc}", retryable=True) from exc
        self._check(resp, "fetch_view")
        return bytes(getattr(resp, "content", b"") or b"")

    def download_bytes(self, url: str) -> bytes:
        """GET an arbitrary (external) URL's raw bytes — used to fetch a start image."""
        try:
            resp = self._transport.request_bytes("GET", url)
        except Exception as exc:
            raise BackendError(_BACKEND, f"download failed: {exc}", retryable=True) from exc
        self._check(resp, "download")
        return bytes(getattr(resp, "content", b"") or b"")

    def object_info(self) -> dict:
        """``GET /object_info`` — the installed-node manifest (best-effort warm)."""
        resp = self._json("GET", "/object_info")
        if not _ok(resp):
            raise BackendError(
                _BACKEND, f"object_info failed (HTTP {_status(resp)})",
                retryable=_status(resp) >= 500,
            )
        return _safe_json(resp)

    def interrupt(self) -> None:
        """``POST /interrupt`` — stop the currently-executing prompt (best-effort)."""
        self._json("POST", "/interrupt", json={})

    def clear_queued(self, prompt_id: str) -> None:
        """``POST /queue`` ``{delete: [prompt_id]}`` — drop a still-queued prompt."""
        self._json("POST", "/queue", json={"delete": [str(prompt_id)]})

    @staticmethod
    def new_client_id() -> str:
        return uuid.uuid4().hex
