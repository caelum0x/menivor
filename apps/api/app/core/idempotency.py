"""Durable, caller-scoped idempotency for product create commands."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request
from sqlalchemy.exc import IntegrityError

from app.models.db.repositories import JobRequestRepository
from app.models.exception import HttpException

IDEMPOTENCY_HEADER = "Idempotency-Key"
MAX_IDEMPOTENCY_KEY_LENGTH = 128


def read_idempotency_key(request: Request, request_id: str) -> str | None:
    """Return a validated key, or ``None`` when the command is not keyed."""
    raw = request.headers.get(IDEMPOTENCY_HEADER)
    if raw is None:
        return None
    key = raw.strip()
    if not key or len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: {IDEMPOTENCY_HEADER} must be between 1 and "
                f"{MAX_IDEMPOTENCY_KEY_LENGTH} characters"
            ),
        )
    return key


def hash_request_payload(payload: Any) -> str:
    """Hash a validated JSON payload using a deterministic representation."""
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def reserve_idempotency_key(
    session: Any,
    user_id: str,
    key: str,
    request_hash: str,
    request_id: str,
) -> tuple[Any, dict[str, Any] | None]:
    """Reserve a key or return the committed response for a safe replay."""
    repository = JobRequestRepository(session)
    existing = repository.get(user_id, key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=(
                    f"{request_id}: idempotency key was already used for a "
                    "different request"
                ),
            )
        return existing, dict(existing.response_data or {})

    try:
        with session.begin_nested():
            row = repository.create(user_id, key, request_hash)
    except IntegrityError:
        existing = repository.get(user_id, key)
        if existing is None:  # pragma: no cover - defensive database anomaly
            raise
        if existing.request_hash != request_hash:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=(
                    f"{request_id}: idempotency key was already used for a "
                    "different request"
                ),
            )
        return existing, dict(existing.response_data or {})
    return row, None


__all__ = [
    "IDEMPOTENCY_HEADER",
    "MAX_IDEMPOTENCY_KEY_LENGTH",
    "hash_request_payload",
    "read_idempotency_key",
    "reserve_idempotency_key",
]
