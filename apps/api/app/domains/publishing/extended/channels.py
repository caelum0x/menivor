"""Connect, verify, share and post to Telegram / Discord / Mastodon channels.

These channels do not use OAuth. The creator pastes a credential, it is
verified against the platform right away, then stored encrypted in
``social_channel_credentials`` (one row per channel; several per platform are
fine, e.g. a Telegram channel per app we market).

Access:

* a personal channel (``workspace_id`` NULL) is visible only to its owner;
* a workspace channel is visible to every member of that workspace, and
  members with an ``owner`` / ``admin`` / ``editor`` role may post to it.
  Only its owner or a workspace ``owner`` / ``admin`` may remove it.

Posts reuse :class:`~.models.PlatformPost` (``platform`` = channel kind,
``target_id`` = channel id), so scheduling, retries, the due-runner, the
calendar and the post history all work unchanged. A text-only post has an
empty ``job_id``.

No token ever leaves this module in a record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import or_, select

from . import repository as repo
from .catalog import CHANNEL_PLATFORMS, DISCORD, MASTODON, TELEGRAM, spec_for
from .channel_models import (
    STATUS_CONNECTED,
    STATUS_ERROR,
    STATUS_NEEDS_REAUTH,
    SocialChannelCredential,
)
from .connections import Credentials
from .connectors import discord as discord_api
from .connectors import mastodon as mastodon_api
from .connectors import telegram as telegram_api
from .connectors.base import PublishError, Transport
from .formats import fit
from .models import POST_CANCELED, POST_SCHEDULED, PlatformPost
from .oauth import ConnectError

try:
    from app.models.db.base import get_session
    from app.services import crypto_tokens

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - import-safe; callers get a clear 503
    get_session = None  # type: ignore[assignment]
    crypto_tokens = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

MAX_CHANNELS_PER_USER = 50
MAX_CHANNELS_PER_POST = 10
MAX_SCHEDULE_AHEAD = timedelta(days=365)
POSTING_ROLES = frozenset({"owner", "admin", "editor"})
MANAGING_ROLES = frozenset({"owner", "admin"})


class ChannelError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400, details: list | None = None) -> None:
        self.status_code = status_code
        self.details = details or []
        super().__init__(message)


def require_ready() -> None:
    if get_session is None or crypto_tokens is None:
        raise ChannelError(f"channel persistence unavailable: {_IMPORT_ERROR}", status_code=503)
    if not crypto_tokens.is_configured():
        raise ChannelError("channel connections are not set up on this server (token key missing)",
                           status_code=503)


def _enc_secret(secret: dict) -> str:
    return crypto_tokens.encrypt(json.dumps(secret, separators=(",", ":")))  # type: ignore[union-attr]


def _dec_secret(blob: str | None) -> dict:
    if not blob:
        return {}
    try:
        value = json.loads(crypto_tokens.decrypt(blob))  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - wrong key / corrupt blob reads as "reconnect"
        return {}
    return value if isinstance(value, dict) else {}


def _iso(value: datetime | None) -> str | None:
    return repo.aware(value).isoformat() if value else None


# --------------------------------------------------------------------------- #
# Access
# --------------------------------------------------------------------------- #
def _memberships(session: Any, user_id: str) -> dict[str, str]:
    """``{workspace_id: role}`` for the user (empty when workspaces are unavailable)."""
    try:
        from app.models.db.models import WorkspaceMember
    except Exception:  # pragma: no cover - core models always import in practice
        return {}
    rows = session.execute(
        select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(WorkspaceMember.user_id == user_id)
    ).all()
    return {str(ws): str(role or "") for ws, role in rows}


def _visible_query(user_id: str, workspace_ids: list[str]):
    cond = SocialChannelCredential.user_id == user_id
    if workspace_ids:
        cond = or_(cond, SocialChannelCredential.workspace_id.in_(workspace_ids))
    return select(SocialChannelCredential).where(cond)


def _can_post(row: SocialChannelCredential, user_id: str, roles: dict[str, str]) -> bool:
    if row.user_id == user_id:
        return True
    return bool(row.workspace_id) and roles.get(str(row.workspace_id), "") in POSTING_ROLES


def _can_manage(row: SocialChannelCredential, user_id: str, roles: dict[str, str]) -> bool:
    if row.user_id == user_id:
        return True
    return bool(row.workspace_id) and roles.get(str(row.workspace_id), "") in MANAGING_ROLES


def _get_visible(session: Any, user_id: str, channel_id: str) -> tuple[SocialChannelCredential, dict[str, str]]:
    roles = _memberships(session, user_id)
    row = session.get(SocialChannelCredential, channel_id)
    if row is None or not (row.user_id == user_id or (row.workspace_id and str(row.workspace_id) in roles)):
        raise ChannelError("channel not found", status_code=404)
    return row, roles


# --------------------------------------------------------------------------- #
# Records (token-free)
# --------------------------------------------------------------------------- #
def channel_record(row: SocialChannelCredential, user_id: str = "", roles: dict[str, str] | None = None) -> dict:
    spec = spec_for(row.kind)
    meta = dict(row.meta or {})
    roles = roles or {}
    return {
        "id": row.id,
        "kind": row.kind,
        "kind_label": spec.label if spec else row.kind,
        "label": row.label or row.target_name or row.kind,
        "status": row.status,
        "target_id": row.target_id,
        "target_name": row.target_name,
        "instance_url": row.instance_url or "",
        "workspace_id": row.workspace_id,
        "shared": bool(row.workspace_id),
        "mine": row.user_id == user_id,
        "can_post": _can_post(row, user_id, roles) and row.status == STATUS_CONNECTED,
        "can_manage": _can_manage(row, user_id, roles),
        "public_url": str(meta.get("public_url") or ""),
        "inbox": {
            "reads": bool(meta.get("inbox_reader")),
            "note": str(meta.get("inbox_note") or ""),
        },
        "caption_max": int(meta.get("max_characters") or (spec.rules.caption_max if spec else 0)),
        "last_verified_at": _iso(row.last_verified_at),
        "last_error": row.last_error or "",
        "created_at": _iso(row.created_at),
    }


def list_channels(user_id: str) -> dict:
    require_ready()
    with get_session() as session:  # type: ignore[misc]
        roles = _memberships(session, user_id)
        rows = session.execute(
            _visible_query(user_id, list(roles)).order_by(SocialChannelCredential.created_at.asc())
        ).scalars().all()
        return {
            "channels": [channel_record(r, user_id, roles) for r in rows],
            "kinds": [kind_info(k) for k in CHANNEL_PLATFORMS],
        }


_KIND_HELP = {
    TELEGRAM: (
        "Create a bot with @BotFather, add it as an admin of your channel (or a member of your group), then "
        "paste the bot token and the channel's @username or numeric id. To see replies here, link a discussion "
        "group to the channel and add the bot to it too."
    ),
    DISCORD: (
        "In the channel's settings open Integrations -> Webhooks, create a webhook and paste its URL. Posting "
        "needs nothing else. To read replies here, also paste a bot token and the channel id (the bot needs "
        "'Read Message History' and the Message Content intent turned on in the Developer Portal)."
    ),
    MASTODON: (
        "On your instance open Preferences -> Development -> New application with the 'read' and 'write' "
        "scopes, then paste the instance address and the application's access token."
    ),
}


def kind_info(kind: str) -> dict:
    spec = spec_for(kind)
    assert spec is not None
    return {
        "kind": kind,
        "label": spec.label,
        "auth": spec.auth,
        "help": _KIND_HELP.get(kind, ""),
        "rules": spec.rules.to_record(),
        "docs_url": spec.docs_url,
        "cost_note": "Free: this platform's API has no fees and needs no app review.",
    }


# --------------------------------------------------------------------------- #
# Connect
# --------------------------------------------------------------------------- #
def _check_workspace(session: Any, user_id: str, workspace_id: str | None) -> str | None:
    if not workspace_id:
        return None
    role = _memberships(session, user_id).get(workspace_id, "")
    if role not in MANAGING_ROLES:
        raise ChannelError("only workspace owners and admins can share a channel with the workspace",
                           status_code=403)
    return workspace_id


def _store(user_id: str, *, kind: str, label: str, secret: dict, target_id: str, target_name: str,
           instance_url: str = "", meta: dict | None = None, workspace_id: str | None = None) -> dict:
    now = repo.utcnow()
    with get_session() as session:  # type: ignore[misc]
        ws = _check_workspace(session, user_id, workspace_id)
        existing = session.execute(
            select(SocialChannelCredential).where(
                SocialChannelCredential.user_id == user_id,
                SocialChannelCredential.kind == kind,
                SocialChannelCredential.target_id == target_id,
            )
        ).scalar_one_or_none()
        if existing is None:
            count = session.execute(
                select(SocialChannelCredential.id).where(SocialChannelCredential.user_id == user_id)
            ).all()
            if len(count) >= MAX_CHANNELS_PER_USER:
                raise ChannelError(f"at most {MAX_CHANNELS_PER_USER} channels per account", status_code=409)
            existing = SocialChannelCredential(user_id=user_id, kind=kind, credentials_enc="", meta={})
            session.add(existing)
        existing.label = (label or target_name or kind)[:200]
        existing.status = STATUS_CONNECTED
        existing.credentials_enc = _enc_secret(secret)
        existing.instance_url = instance_url or ""
        existing.target_id = target_id[:200]
        existing.target_name = (target_name or "")[:200]
        existing.meta = {**dict(existing.meta or {}), **(meta or {})}
        existing.workspace_id = ws
        existing.last_verified_at = now
        existing.last_error = ""
        session.flush()
        record = channel_record(existing, user_id, _memberships(session, user_id))
        channel_id = existing.id
    _ensure_inbox(user_id, channel_id)
    return record


def _ensure_inbox(user_id: str, channel_id: str) -> None:
    try:
        from app.domains.social_inbox import channel_inbox

        channel_inbox.ensure_channel_post_for(user_id, channel_id)
    except Exception as exc:  # noqa: BLE001 - posting works without the inbox
        logger.info(f"channels: inbox tracking skipped for {channel_id}: {exc}")


def _publish_error(exc: PublishError) -> ChannelError:
    message = str(exc).split("] ", 1)[-1]
    return ChannelError(message, status_code=503 if exc.retryable else 422)


def connect_telegram(user_id: str, bot_token: str, chat_id: str, *, label: str = "",
                     workspace_id: str | None = None, transport: Transport) -> dict:
    require_ready()
    token = str(bot_token or "").strip()
    try:
        info = telegram_api.verify(token, chat_id, transport=transport)
    except PublishError as exc:
        raise _publish_error(exc) from exc
    return _store(
        user_id, kind=TELEGRAM, label=label or info.title, secret={"bot_token": token},
        target_id=info.chat_id, target_name=info.title, workspace_id=workspace_id,
        meta={
            "bot_id": info.bot_id, "bot_username": info.bot_username, "chat_type": info.chat_type,
            "username": info.username, "linked_chat_id": info.linked_chat_id,
            "public_url": f"https://t.me/{info.username}" if info.username else "",
            "inbox_reader": True,
            "inbox_note": (
                "Direct messages to the bot and comments in the channel's linked discussion group appear in the "
                "inbox. The bot must be in the discussion group, and no other service may use this bot's webhook."
            ),
        },
    )


def connect_discord(user_id: str, webhook_url: str, *, label: str = "", bot_token: str = "",
                    channel_id: str = "", workspace_id: str | None = None, transport: Transport) -> dict:
    require_ready()
    hook = discord_api.parse_webhook(webhook_url)
    if hook is None:
        raise ChannelError("Paste the full webhook URL (https://discord.com/api/webhooks/...).", status_code=422)
    try:
        info = discord_api.verify(hook.url, transport=transport)
        channel_name, bot_user_id = "", ""
        read_channel = str(channel_id or info.channel_id or "").strip()
        if bot_token:
            channel_name, bot_user_id = discord_api.verify_bot(bot_token.strip(), read_channel,
                                                               transport=transport)
    except PublishError as exc:
        raise _publish_error(exc) from exc
    secret = {"webhook_url": hook.url}
    if bot_token:
        secret["bot_token"] = bot_token.strip()
    name = f"#{channel_name}" if channel_name else (info.name or "Discord channel")
    return _store(
        user_id, kind=DISCORD, label=label or name, secret=secret, target_id=info.webhook_id,
        target_name=name, workspace_id=workspace_id,
        meta={
            "guild_id": info.guild_id, "channel_id": read_channel or info.channel_id, "webhook_name": info.name,
            "bot_user_id": bot_user_id,
            "inbox_reader": bool(bot_token),
            "inbox_note": (
                "Replies to posts in this channel appear in the inbox." if bot_token else
                "Posting only. Add a bot token to see replies in the inbox (webhooks cannot read messages)."
            ),
        },
    )


def connect_mastodon(user_id: str, instance: str, access_token: str, *, label: str = "",
                     visibility: str = "public", workspace_id: str | None = None, transport: Transport,
                     resolve: Any = mastodon_api._default_resolver) -> dict:  # noqa: SLF001
    require_ready()
    token = str(access_token or "").strip()
    try:
        instance_url = mastodon_api.normalize_instance(instance, resolve=resolve)
        account = mastodon_api.verify(instance_url, token, transport=transport)
    except PublishError as exc:
        raise _publish_error(exc) from exc
    host = instance_url.removeprefix("https://")
    handle = f"@{account.username}@{host}"
    return _store(
        user_id, kind=MASTODON, label=label or handle, secret={"access_token": token},
        target_id=account.id or handle, target_name=handle, instance_url=instance_url, workspace_id=workspace_id,
        meta={
            "instance_url": instance_url, "username": account.username, "acct": account.acct,
            "public_url": account.url, "max_characters": account.max_characters,
            "visibility": visibility if visibility in mastodon_api.VISIBILITIES else "public",
            "inbox_reader": True,
            "inbox_note": "Mentions and direct messages to this account appear in the inbox.",
        },
    )


def disconnect(user_id: str, channel_id: str) -> dict:
    """Remove a channel, cancel its not-yet-started posts, and drop its inbox tracking."""
    require_ready()
    with get_session() as session:  # type: ignore[misc]
        row, roles = _get_visible(session, user_id, channel_id)
        if not _can_manage(row, user_id, roles):
            raise ChannelError("only the channel's owner or a workspace admin can remove it", status_code=403)
        kind = row.kind
        pending = session.execute(
            select(PlatformPost).where(
                PlatformPost.platform == kind, PlatformPost.target_id == channel_id,
                PlatformPost.status == POST_SCHEDULED, PlatformPost.attempts == 0,
            )
        ).scalars().all()
        for post in pending:
            post.status = POST_CANCELED
            post.next_attempt_at = None
            post.error = "The channel was disconnected."
        session.delete(row)
        session.flush()
    try:
        from app.domains.social_inbox import channel_inbox

        channel_inbox.drop_channel_post(user_id, kind, channel_id)
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.info(f"channels: inbox cleanup skipped for {channel_id}: {exc}")
    return {"id": channel_id, "disconnected": True, "canceled_posts": len(pending)}


def reverify(user_id: str, channel_id: str, *, transport: Transport) -> dict:
    """Re-check a stored credential and update the channel's status."""
    require_ready()
    with get_session() as session:  # type: ignore[misc]
        row, roles = _get_visible(session, user_id, channel_id)
        if not _can_manage(row, user_id, roles):
            raise ChannelError("only the channel's owner or a workspace admin can re-check it", status_code=403)
        kind, target_id, instance = row.kind, row.target_id, row.instance_url
        secret = _dec_secret(row.credentials_enc)
    error = ""
    reauth = False
    try:
        if not secret:
            raise PublishError(kind, "The stored credential cannot be read. Reconnect the channel.")
        if kind == TELEGRAM:
            telegram_api.verify(secret.get("bot_token", ""), target_id, transport=transport)
        elif kind == DISCORD:
            discord_api.verify(secret.get("webhook_url", ""), transport=transport)
        elif kind == MASTODON:
            mastodon_api.verify(instance, secret.get("access_token", ""), transport=transport)
    except PublishError as exc:
        error = str(exc).split("] ", 1)[-1]
        reauth = not exc.retryable
    with get_session() as session:  # type: ignore[misc]
        row = session.get(SocialChannelCredential, channel_id)
        if row is None:
            raise ChannelError("channel not found", status_code=404)
        row.last_verified_at = repo.utcnow()
        row.last_error = error[:1000]
        row.status = STATUS_CONNECTED if not error else (STATUS_NEEDS_REAUTH if reauth else STATUS_ERROR)
        session.flush()
        return channel_record(row, user_id, _memberships(session, user_id))


# --------------------------------------------------------------------------- #
# Credentials for the due-runner
# --------------------------------------------------------------------------- #
def post_credentials(user_id: str, kind: str, channel_id: str) -> Credentials:
    """Decrypted credentials for one channel post; raises :class:`ConnectError` when unusable."""
    require_ready()
    label = spec_for(kind).label if spec_for(kind) else kind
    with get_session() as session:  # type: ignore[misc]
        roles = _memberships(session, user_id)
        row = session.get(SocialChannelCredential, channel_id) if channel_id else None
        if row is None or row.kind != kind or not _can_post(row, user_id, roles):
            raise ConnectError(f"the {label} channel for this post was removed or is no longer shared with you",
                               status_code=409)
        if row.status == STATUS_NEEDS_REAUTH:
            raise ConnectError(row.last_error or f"reconnect the {label} channel", status_code=409, reauth=True)
        secret = _dec_secret(row.credentials_enc)
        meta = {**dict(row.meta or {}), "instance_url": row.instance_url or ""}
        target_id = row.target_id
    main = {TELEGRAM: "bot_token", DISCORD: "webhook_url", MASTODON: "access_token"}.get(kind, "")
    token = str(secret.get(main) or "")
    if not token:
        raise ConnectError(f"the {label} credential cannot be read; reconnect the channel", status_code=409,
                           reauth=True)
    return Credentials(platform=kind, access_token=token, target_id=target_id, external_account_id=target_id,
                       meta=meta)


def channel_secret(channel_id: str) -> tuple[SocialChannelCredential | None, dict]:
    """Detached row + decrypted secret, for the inbox (caller has already checked ownership)."""
    require_ready()
    with get_session() as session:  # type: ignore[misc]
        row = session.get(SocialChannelCredential, channel_id)
        if row is None:
            return None, {}
        secret = _dec_secret(row.credentials_enc)
        session.expunge(row)
        return row, secret


def save_meta(channel_id: str, updates: dict) -> None:
    """Merge non-secret ``updates`` into the channel's ``meta`` (new dict; JSON is replace-on-edit)."""
    with get_session() as session:  # type: ignore[misc]
        row = session.get(SocialChannelCredential, channel_id)
        if row is not None:
            row.meta = {**dict(row.meta or {}), **updates}


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ChannelDraft:
    channel_id: str
    caption: str = ""
    hashtags: tuple[str, ...] = ()


def create_posts(user_id: str, drafts: list[ChannelDraft], *, job_id: str = "",
                 scheduled_at: datetime | None = None, now: datetime | None = None,
                 tone: str = "as_written") -> list[dict]:
    """Validate every channel, then queue one post per channel (all or nothing).

    ``tone`` applies the calendar's deterministic rewrite (:mod:`..tone`) to each
    caption server-side, so what is posted always matches the preview.
    """
    require_ready()
    from ..tone import apply_tone
    from .posts import _enqueue, post_record

    moment = now or repo.utcnow()
    if not drafts:
        raise ChannelError("choose at least one channel")
    if len(drafts) > MAX_CHANNELS_PER_POST:
        raise ChannelError(f"at most {MAX_CHANNELS_PER_POST} channels per post")
    ids = [d.channel_id for d in drafts]
    if len(set(ids)) != len(ids):
        raise ChannelError("each channel can appear once")
    when = repo.aware(scheduled_at) or moment
    if when < moment - timedelta(minutes=1):
        raise ChannelError("the scheduled time is in the past")
    if when > moment + MAX_SCHEDULE_AHEAD:
        raise ChannelError("schedule at most a year ahead")
    if job_id:
        from app.domains.publishing.native_service import NativePublishError, _resolve_final_key

        try:
            _resolve_final_key(user_id, job_id)  # owner-scoped; must be a complete render
        except NativePublishError as exc:
            raise ChannelError(str(exc), status_code=exc.status_code) from exc

    problems: list[dict] = []
    ready: list[tuple[SocialChannelCredential, Any]] = []
    with get_session() as session:  # type: ignore[misc]
        roles = _memberships(session, user_id)
        for draft in drafts:
            row = session.get(SocialChannelCredential, draft.channel_id)
            if row is None or not (row.user_id == user_id or (row.workspace_id and str(row.workspace_id) in roles)):
                problems.append({"channel_id": draft.channel_id, "message": "channel not found"})
                continue
            if not _can_post(row, user_id, roles):
                problems.append({"channel_id": row.id, "message": "your workspace role cannot post here"})
                continue
            if row.status != STATUS_CONNECTED:
                problems.append({"channel_id": row.id, "message": row.last_error or "reconnect this channel"})
                continue
            result = fit(row.kind, caption=apply_tone(draft.caption, tone), hashtags=draft.hashtags)
            limit = int((row.meta or {}).get("max_characters") or 0)
            if row.kind == MASTODON and limit and result.length > limit:
                problems.append({"channel_id": row.id, "message": f"this instance allows {limit} characters"})
                continue
            if not job_id and not result.text.strip():
                problems.append({"channel_id": row.id, "message": "add text or a finished reel"})
                continue
            if not result.ok:
                problems.append({"channel_id": row.id, "message": "; ".join(i.message for i in result.issues)})
                continue
            ready.append((row, result))
        if problems:
            raise ChannelError("some channels can't take this post yet", status_code=409, details=problems)
        records = []
        for row, result in ready:
            post = repo.add_post(
                session, user_id=user_id, job_id=job_id or "", platform=row.kind, status=POST_SCHEDULED,
                scheduled_at=when, next_attempt_at=when, title="", text=result.text,
                hashtags=list(result.hashtags), target_id=row.id,
            )
            records.append({**post_record(post), "channel_label": row.label or row.target_name})
    if when <= moment + timedelta(seconds=5):
        for record in records:
            _enqueue(record["id"])
    return records


def send_test(user_id: str, channel_id: str, text: str, *, transport: Transport) -> dict:
    """Post a short text right now (synchronously) and return the finished post record."""
    from .posts import post_record, run_post

    body = str(text or "").strip() or "Test post from Menivor. The channel is connected."
    created = create_posts(user_id, [ChannelDraft(channel_id=channel_id, caption=body)])
    result = run_post(created[0]["id"], transport=transport)
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_post(session, user_id, created[0]["id"])
        record = post_record(row) if row is not None else {**created[0], "status": result.get("status")}
    return record
