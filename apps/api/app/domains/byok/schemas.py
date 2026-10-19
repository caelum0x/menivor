"""BYOK DTOs — add-key request + a strictly secret-free key view."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AddProviderKeyRequest(BaseModel):
    """Store a customer's own provider API key (the secret is write-only)."""

    model_config = ConfigDict(extra="forbid")

    provider_key: str = Field(..., description="Provider key, e.g. 'openrouter'")
    secret: str = Field(..., min_length=1, description="The raw API key (never stored raw)")
    label: str = Field(default="", description="Optional display label")
    priority: int = Field(default=0, description="Routing priority (higher wins)")


def mask_secret(secret: str) -> str:
    """Return a non-secret display hint, e.g. ``sk-…AB``. Never the full key."""
    s = str(secret or "")
    if len(s) <= 6:
        return "…"
    return f"{s[:3]}…{s[-2:]}"


def key_view(key: object) -> dict:
    """Client-facing key shape. NEVER includes the ciphertext or raw secret."""
    last_used = getattr(key, "last_used_at", None)
    created = getattr(key, "created_at", None)
    return {
        "id": getattr(key, "id", ""),
        "provider_key": getattr(key, "provider_key", ""),
        "label": getattr(key, "label", ""),
        "key_prefix": getattr(key, "key_prefix", ""),
        "scope": getattr(key, "scope", "generation"),
        "priority": int(getattr(key, "priority", 0) or 0),
        "status": getattr(key, "status", "active"),
        "use_count": int(getattr(key, "use_count", 0) or 0),
        "last_used_at": last_used.isoformat() if hasattr(last_used, "isoformat") else None,
        "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
    }
