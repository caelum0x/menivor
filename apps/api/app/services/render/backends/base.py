"""``RenderBackend`` protocol + registry + the HTTP transport seam.

A backend is the adapter between the unified envelope and a concrete async-GPU
service (RunPod, worker-comfyui, comfyui-deploy, Replicate, Fal, ViewComfy). Each
implements four verbs — ``submit`` / ``poll`` / ``cancel`` / ``warm`` — returning
normalized :class:`~app.services.render.envelope.RenderJob`s. The only thing that
touches the network is the injectable :class:`Transport`, so backend logic is
unit-testable against a fake transport (that is the network boundary, not a stub).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.services.render.envelope import RenderJob


class BackendError(RuntimeError):
    """A backend call failed (bad request, auth, or an unexpected payload)."""

    def __init__(self, backend: str, message: str, *, retryable: bool = False) -> None:
        self.backend = backend
        self.retryable = retryable
        super().__init__(f"[{backend}] {message}")


@runtime_checkable
class HttpResponse(Protocol):
    status_code: int
    headers: Any

    def json(self) -> Any: ...

    @property
    def text(self) -> str: ...


@runtime_checkable
class Transport(Protocol):
    """The single network seam every backend uses."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        json: Any | None = None,
    ) -> HttpResponse: ...


class RequestsTransport:
    """Default :class:`Transport` backed by ``requests`` (lazy import)."""

    def __init__(self, timeout_s: float = 60.0) -> None:
        self._timeout = timeout_s

    def request(self, method, url, *, headers=None, params=None, json=None) -> HttpResponse:
        import requests

        return requests.request(
            method, url, headers=headers, params=params, json=json, timeout=self._timeout
        )


@runtime_checkable
class RenderBackend(Protocol):
    """Adapter from the unified envelope to a concrete async-GPU service."""

    name: str

    def submit(self, spec: dict, *, transport: Transport) -> RenderJob: ...

    def poll(self, job: RenderJob, *, transport: Transport) -> RenderJob: ...

    def cancel(self, job: RenderJob, *, transport: Transport) -> RenderJob: ...

    def warm(self, model: str, *, transport: Transport) -> bool: ...


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, RenderBackend] = {}


def register_backend(backend: RenderBackend) -> None:
    _REGISTRY[backend.name] = backend


def get_backend(name: str) -> RenderBackend | None:
    return _REGISTRY.get(str(name or "").strip().lower())


def available_backends() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def ok(resp: HttpResponse) -> bool:
    return 200 <= int(getattr(resp, "status_code", 0)) < 300


def safe_json(resp: HttpResponse) -> dict:
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {"data": body}
    except Exception:
        return {}
