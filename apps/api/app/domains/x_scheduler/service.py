"""Connect, disconnect, list X accounts, and schedule one finished render.

The plaintext API key exists only inside this module, long enough to call
Buffer or Typefully. It is encrypted before insert and never returned.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.x_scheduler.buffer_client import BufferClient
from app.domains.x_scheduler.errors import LimitReached, SchedulerError, redact
from app.domains.x_scheduler.http import ProviderHTTPError
from app.domains.x_scheduler.media import buffer_asset_url, read_bytes, resolve
from app.domains.x_scheduler.models import PROVIDERS, SchedulerConnection
from app.domains.x_scheduler.typefully_client import TypefullyClient
from app.services import crypto_tokens

X_CAPTION_MAX = 280
_WHEN = ("now", "queue", "schedule")


def hint_for(secret: str) -> str:
    tail = str(secret or "")[-4:]
    if len(tail) < 4:
        return "••••"
    return f"••••{tail}"


def connection_view(row: SchedulerConnection) -> dict:
    created = row.created_at.isoformat() if row.created_at else None
    return {
        "provider": row.provider,
        "connected": True,
        "key_hint": row.key_hint or "",
        "created_at": created,
    }


def list_connections(session: Session, user_id: str) -> list[dict]:
    rows = session.scalars(
        select(SchedulerConnection).where(SchedulerConnection.user_id == user_id)
    ).all()
    by_provider = {row.provider: connection_view(row) for row in rows}
    return [
        by_provider.get(provider) or {"provider": provider, "connected": False, "key_hint": "", "created_at": None}
        for provider in PROVIDERS
    ]


def connect(session: Session, user_id: str, provider: str, api_key: str) -> dict:
    provider = _provider(provider)
    secret = str(api_key or "").strip()
    if not secret or len(secret) > 512 or any(ch.isspace() for ch in secret):
        raise SchedulerError(400, "Paste the API key from your Buffer or Typefully account.")
    try:
        _verify(provider, secret)
    except LimitReached:
        raise
    except ProviderHTTPError as exc:
        raise SchedulerError(exc.status if exc.status in (401, 403) else 400, redact(exc.message, secret)) from exc
    try:
        ciphertext = crypto_tokens.encrypt(secret)
    except Exception as exc:  # noqa: BLE001 - never persist a plaintext key
        raise SchedulerError(
            503,
            "Key storage is not configured. Set SOCIAL_TOKEN_KEY on the API before saving a key.",
        ) from exc
    row = session.scalar(
        select(SchedulerConnection).where(
            SchedulerConnection.user_id == user_id,
            SchedulerConnection.provider == provider,
        )
    )
    if row is None:
        row = SchedulerConnection(
            user_id=user_id,
            provider=provider,
            key_hint=hint_for(secret),
            encrypted_secret=ciphertext,
        )
        session.add(row)
    else:
        row.key_hint = hint_for(secret)
        row.encrypted_secret = ciphertext
        row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return connection_view(row)


def disconnect(session: Session, user_id: str, provider: str) -> dict:
    provider = _provider(provider)
    row = session.scalar(
        select(SchedulerConnection).where(
            SchedulerConnection.user_id == user_id,
            SchedulerConnection.provider == provider,
        )
    )
    if row is None:
        raise SchedulerError(404, "That account is not connected.")
    session.delete(row)
    session.flush()
    return {"provider": provider, "connected": False}


def list_targets(session: Session, user_id: str, provider: str) -> dict:
    provider = _provider(provider)
    secret = _secret(session, user_id, provider)
    try:
        targets = _verify(provider, secret)
    except ProviderHTTPError as exc:
        raise SchedulerError(exc.status if exc.status < 500 else 502, redact(exc.message, secret)) from exc
    return {"provider": provider, "targets": targets}


def schedule_post(
    session: Session,
    user_id: str,
    *,
    provider: str,
    target_id: str,
    source: str,
    source_id: str,
    caption: str,
    when: str,
    scheduled_at: datetime | None,
) -> dict:
    provider = _provider(provider)
    when = str(when or "").strip()
    if when not in _WHEN:
        raise SchedulerError(400, "Choose post now, add to queue, or a date and time.")
    text = str(caption or "")
    if len(text) > X_CAPTION_MAX:
        raise SchedulerError(400, "X posts are limited to 280 characters.")
    target_id = str(target_id or "").strip()
    if not target_id or len(target_id) > 128:
        raise SchedulerError(400, "Choose an X account.")
    due_at = _due_at(when, scheduled_at)
    secret = _secret(session, user_id, provider)
    asset = resolve(session, user_id, source, source_id)
    note = ""
    try:
        if provider == "buffer":
            url, note = buffer_asset_url(asset, when)
            created = BufferClient(secret).create_post(
                channel_id=target_id, text=text, asset_url=url, kind=asset.kind, when=when, due_at=due_at,
            )
        else:
            created = TypefullyClient(secret).publish(
                social_set_id=target_id,
                text=text,
                filename=asset.filename,
                data=read_bytes(asset),
                when=when,
                due_at=due_at,
            )
    except LimitReached:
        raise
    except ProviderHTTPError as exc:
        status = 401 if exc.status in (401, 403) else 429 if exc.status == 429 else 422 if exc.status < 500 else 502
        raise SchedulerError(status, redact(exc.message, secret)) from exc
    extra = note
    private_url = str(created.get("private_url") or "")
    if private_url:
        extra = f"{extra} Draft: {private_url}".strip()
    return {
        "provider": provider,
        "target_id": target_id,
        "external_id": created.get("id") or "",
        "status": created.get("status") or "scheduled",
        "when": when,
        "private_url": private_url,
        "message": _message(provider, when, note=extra),
    }


def client_for(provider: str, api_key: str):
    if provider == "buffer":
        return BufferClient(api_key)
    return TypefullyClient(api_key)


def _verify(provider: str, secret: str) -> list[dict]:
    return client_for(provider, secret).list_x_channels() if provider == "buffer" else client_for(provider, secret).list_x_social_sets()


def _secret(session: Session, user_id: str, provider: str) -> str:
    row = session.scalar(
        select(SchedulerConnection).where(
            SchedulerConnection.user_id == user_id,
            SchedulerConnection.provider == provider,
        )
    )
    if row is None:
        name = "Buffer" if provider == "buffer" else "Typefully"
        raise SchedulerError(400, f"Connect your {name} API key in settings first.")
    try:
        return crypto_tokens.decrypt(row.encrypted_secret)
    except Exception as exc:  # noqa: BLE001
        raise SchedulerError(503, "The saved key could not be read. Disconnect it and paste it again.") from exc


def _provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    if provider not in PROVIDERS:
        raise SchedulerError(400, "provider must be buffer or typefully")
    return provider


def _due_at(when: str, scheduled_at: datetime | None) -> str | None:
    if when != "schedule":
        return None
    if scheduled_at is None:
        raise SchedulerError(400, "Pick a date and time.")
    when_at = scheduled_at if scheduled_at.tzinfo else scheduled_at.replace(tzinfo=timezone.utc)
    if when_at <= datetime.now(timezone.utc):
        raise SchedulerError(400, "Pick a time in the future.")
    return when_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _message(provider: str, when: str, note: str | None) -> str:
    name = "Buffer" if provider == "buffer" else "Typefully"
    if when == "now":
        text = f"{name} is publishing this to X now."
    elif when == "queue":
        text = f"Added to your {name} queue. {name} will post it to X in the next free slot."
    else:
        text = f"Scheduled in {name}. {name} will post it to X at that time."
    if note:
        text = f"{text} {note}"
    return text
