"""Unified async-GPU render orchestration.

The envelope (``envelope``) + backend protocol (``backends.base``) + client
(``job_client``) give the platform one state machine and one client for every
async generation backend. Importing this package registers the built-in backends.
"""

from __future__ import annotations

from app.services.render.backends import local_comfyui  # noqa: F401 - registers the backend
from app.services.render.backends import rocketride  # noqa: F401 - registers the backend
from app.services.render.backends import runpod  # noqa: F401 - registers the backend
from app.services.render.backends.base import (
    RenderBackend,
    RequestsTransport,
    Transport,
    available_backends,
    get_backend,
    register_backend,
)
from app.services.render.envelope import (
    ALL_STATES,
    CANCELLED,
    COMPLETED,
    FAILED,
    IN_PROGRESS,
    IN_QUEUE,
    TERMINAL_STATES,
    RenderJob,
    can_transition,
    normalize_state,
    transition,
)
from app.services.render.job_client import (
    apply_webhook,
    cancel,
    poll,
    sign_webhook,
    submit,
    verify_webhook,
)

__all__ = [
    "ALL_STATES", "CANCELLED", "COMPLETED", "FAILED", "IN_PROGRESS", "IN_QUEUE",
    "TERMINAL_STATES", "RenderJob", "can_transition", "normalize_state", "transition",
    "RenderBackend", "RequestsTransport", "Transport", "available_backends",
    "get_backend", "register_backend",
    "apply_webhook", "cancel", "poll", "sign_webhook", "submit", "verify_webhook",
]
