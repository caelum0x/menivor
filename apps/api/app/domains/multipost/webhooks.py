"""TikTok webhooks for Content Posting status (``post.publish.*``).

Docs: https://developers.tiktok.com/doc/webhooks-verification

TikTok signs each delivery: header ``TikTok-Signature: t=<unix>,s=<hex>`` where
``s = HMAC_SHA256(client_secret, f"{t}.{raw_body}")``. Deliveries older than the
tolerance are refused; a delivery already applied is acknowledged without
re-applying (dedupe on the body hash).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from . import settings
from .clients import tiktok as tt
from .models import (
    POST_FAILED,
    POST_PROCESSING,
    POST_PUBLISHED,
    POST_PUBLISHING,
    TIKTOK,
    MultipostAccount,
    MultipostPost,
    MultipostWebhookEvent,
)

TOLERANCE_S = 300


class WebhookError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.status_code = status_code
        super().__init__(message)


def verify_tiktok(raw: bytes, header: str, *, now: float | None = None) -> None:
    secret = settings.client_secret(TIKTOK)
    if not secret:
        raise WebhookError("TikTok webhooks are not set up on this server", 503)
    parts = dict(p.split("=", 1) for p in str(header or "").split(",") if "=" in p)
    stamp, signature = parts.get("t", ""), parts.get("s", "")
    if not stamp.isdigit() or not signature:
        raise WebhookError("missing signature", 401)
    if abs((now or time.time()) - int(stamp)) > TOLERANCE_S:
        raise WebhookError("stale delivery", 401)
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookError("bad signature", 401)


def _content(payload: dict) -> dict:
    raw = payload.get("content")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def apply_tiktok(session: Any, raw: bytes) -> dict:
    """Apply one verified delivery. Returns what happened (for logs/tests)."""
    event_id = hashlib.sha256(raw).hexdigest()
    if session.get(MultipostWebhookEvent, event_id) is not None:
        return {"applied": False, "reason": "duplicate"}
    try:
        payload = json.loads(raw or b"{}")
    except ValueError as exc:
        raise WebhookError("body is not JSON") from exc
    event = str(payload.get("event") or "")
    content = _content(payload)
    publish_id = str(content.get("publish_id") or "")
    session.add(MultipostWebhookEvent(id=event_id, provider=TIKTOK, event=event[:80], publish_ref=publish_id[:300]))
    if not publish_id or not event.startswith("post.publish."):
        return {"applied": False, "reason": "ignored", "event": event}
    post = session.execute(select(MultipostPost).where(
        MultipostPost.provider == TIKTOK, MultipostPost.publish_ref == publish_id,
    )).scalars().first()
    if post is None:
        return {"applied": False, "reason": "unknown publish", "event": event}
    _transition(session, post, event, content)
    return {"applied": True, "event": event, "post_id": post.id, "status": post.status}


def _transition(session: Any, post: MultipostPost, event: str, content: dict) -> None:
    now = datetime.now(timezone.utc)
    if event == "post.publish.failed":
        if post.status in (POST_PUBLISHING, POST_PROCESSING):
            post.status = POST_FAILED
            post.error = f"TikTok rejected the post: {content.get('reason') or 'unknown reason'}"[:2000]
        post.provider_status = "FAILED"
        return
    if event in ("post.publish.complete", "post.publish.inbox_delivered", "post.publish.publicly_available"):
        post.status = POST_PUBLISHED
        post.published_at = post.published_at or now
        post.error = ""
        post.provider_status = {"post.publish.complete": "PUBLISH_COMPLETE",
                                "post.publish.inbox_delivered": "SEND_TO_USER_INBOX",
                                "post.publish.publicly_available": "PUBLICLY_AVAILABLE"}[event]
        post_id = str(content.get("post_id") or "")
        if post_id:
            account = session.get(MultipostAccount, post.account_id)
            post.external_id = post_id
            post.url = tt.post_url(post_id, account.handle if account else "")
        return
    if event == "post.publish.no_longer_publicaly_available":
        post.provider_status = "NO_LONGER_PUBLIC"
