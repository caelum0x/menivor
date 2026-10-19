"""Backend-agnostic async render client + webhook callback verification.

Thin orchestration over any registered :class:`RenderBackend`: resolve the
backend, submit/poll/cancel a job through the shared transport, and verify signed
webhook callbacks (HMAC-SHA256, constant-time) before trusting a pushed state.
Keeps the envelope the single currency the caller (routing/wallet/event bus) sees.
"""

from __future__ import annotations

import hashlib
import hmac

from app.services.render.backends.base import (
    BackendError,
    RequestsTransport,
    Transport,
    get_backend,
)
from app.services.render.envelope import RenderJob, normalize_state, transition


class RenderClientError(RuntimeError):
    """No such backend, or a backend call could not be completed."""


def _backend_or_raise(name: str):
    backend = get_backend(name)
    if backend is None:
        raise RenderClientError(f"unknown render backend {name!r}")
    return backend


def submit(backend: str, spec: dict, *, transport: Transport | None = None) -> RenderJob:
    """Submit a render spec to ``backend`` and return the queued job."""
    return _backend_or_raise(backend).submit(spec, transport=transport or RequestsTransport())


def poll(job: RenderJob, *, transport: Transport | None = None) -> RenderJob:
    """Advance ``job`` by polling its backend (idempotent once terminal)."""
    if job.is_terminal:
        return job
    return _backend_or_raise(job.backend).poll(job, transport=transport or RequestsTransport())


def cancel(job: RenderJob, *, transport: Transport | None = None) -> RenderJob:
    """Best-effort cancel ``job`` on its backend."""
    try:
        return _backend_or_raise(job.backend).cancel(job, transport=transport or RequestsTransport())
    except BackendError:
        # A cancel that the backend rejects still marks our envelope cancelled.
        return transition(job, "CANCELLED")


def sign_webhook(payload: bytes, secret: str) -> str:
    """Compute the ``sha256=<hex>`` signature we expect on a callback."""
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_webhook(payload: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verification of a webhook body."""
    if not signature or not secret:
        return False
    expected = sign_webhook(payload, secret)
    return hmac.compare_digest(expected, str(signature).strip())


def apply_webhook(
    job: RenderJob,
    raw_state: str,
    *,
    state_map: dict[str, str] | None = None,
    output_refs: tuple[str, ...] | None = None,
    cost_micros: int | None = None,
    error: str = "",
) -> RenderJob:
    """Advance ``job`` from a verified webhook's normalized state.

    Callers MUST verify the signature (``verify_webhook``) before calling this.
    Illegal/duplicate transitions are absorbed by the envelope's idempotent edges.
    """
    target = normalize_state(raw_state, state_map)
    return transition(
        job, target, output_refs=output_refs, cost_micros=cost_micros, error=error
    )
