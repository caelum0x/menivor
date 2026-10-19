"""Instagram API with Instagram Login: Reels via media container + publish.

Docs: https://developers.facebook.com/docs/instagram-platform/content-publishing

1. ``POST /{ig-user-id}/media`` (``media_type=REELS``, public ``video_url``) -> container id.
2. Instagram ingests the video; ``GET /{container}?fields=status_code`` until ``FINISHED``.
3. ``POST /{ig-user-id}/media_publish`` (``creation_id``) -> media id; ``permalink`` read back.

The account's live publishing allowance is read from ``content_publishing_limit``
before each post. The Graph API has no AI-label field, so the AI disclosure is a
caption line (see ``settings.instagram_caption_disclosure``).
"""

from __future__ import annotations

import re

from .base import AuthError, ClientError, PostSpec, PublishOutcome, RateLimited, Transport, body_of, is_ok

GRAPH = "https://graph.instagram.com/v21.0"
# Graph object ids go into URL paths: letters, digits, '_' and '-' only.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_CAPTION = 2200
_AUTH_CODES = {190, 102, 10, 200}
_RATE_CODES = {4, 9, 17, 32, 613}


def _auth(token: str) -> dict:
    """Token in a header, never in the URL (query strings end up in access logs)."""
    return {"Authorization": f"Bearer {token}"}


def _raise_for(resp, what: str) -> dict:
    body = body_of(resp)
    if is_ok(resp) and "error" not in body:
        return body
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    try:
        code = int(err.get("code") or 0)
    except (TypeError, ValueError):
        code = 0
    sub = str(err.get("error_subcode") or "")
    message = str(err.get("error_user_msg") or err.get("message") or f"HTTP {getattr(resp, 'status_code', 0)}")
    status = int(getattr(resp, "status_code", 0) or 0)
    if code in _AUTH_CODES or status == 401:
        raise AuthError("instagram", f"Instagram rejected the connection during {what}: {message}", code=str(code))
    if code in _RATE_CODES or sub == "2207042" or status == 429:
        raise RateLimited("instagram", f"Instagram posting limit reached during {what}: {message}",
                          retry_after_s=3600, code=str(code))
    raise ClientError("instagram", f"Instagram {what} failed: {message}", retryable=status >= 500,
                      code=str(code))


def _user_id(ig_user_id: str) -> str:
    """Instagram user ids are numeric; anything else never reaches a Graph URL path."""
    value = str(ig_user_id or "")
    if not value.isdigit():
        raise ClientError("instagram", "this Instagram account id is not valid; reconnect the account")
    return value


def publishing_quota(token: str, ig_user_id: str, *, transport: Transport) -> tuple[int, int]:
    """``(used, total)`` API posts in the current 24 h window (``(0, 0)`` when unknown)."""
    resp = transport.request("GET", f"{GRAPH}/{_user_id(ig_user_id)}/content_publishing_limit",
                             params={"fields": "quota_usage,config"}, headers=_auth(token))
    if not is_ok(resp):
        return 0, 0
    rows = body_of(resp).get("data") or []
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    config = row.get("config") if isinstance(row.get("config"), dict) else {}
    try:
        return int(row.get("quota_usage") or 0), int(config.get("quota_total") or 0)
    except (TypeError, ValueError):
        return 0, 0


def caption_for(spec: PostSpec, disclosure: str) -> str:
    text = spec.text(MAX_CAPTION)
    if spec.ai_generated and disclosure and disclosure.lower() not in text.lower():
        room = MAX_CAPTION - len(disclosure) - 2
        text = f"{text[:room]}\n\n{disclosure}".strip() if text else disclosure
    return text


def publish(token: str, ig_user_id: str, spec: PostSpec, *, disclosure: str, transport: Transport
            ) -> PublishOutcome:
    """Create the Reels container. Returns ``processing`` with the container id."""
    if not spec.video_url:
        raise ClientError("instagram", "Instagram needs a public video URL")
    ig_user_id = _user_id(ig_user_id)
    used, total = publishing_quota(token, ig_user_id, transport=transport)
    if total and used >= total:
        raise RateLimited("instagram", f"this Instagram account used its {total} API posts for today",
                          retry_after_s=3600)
    resp = transport.request(
        "POST", f"{GRAPH}/{ig_user_id}/media",
        params={
            "media_type": "REELS",
            "video_url": spec.video_url,
            "caption": caption_for(spec, disclosure),
            "share_to_feed": "true",
        },
        headers=_auth(token),
    )
    container = str(_raise_for(resp, "upload").get("id") or "")
    if not container:
        raise ClientError("instagram", "Instagram returned no container id", retryable=True)
    return PublishOutcome(status="processing", ref=container, provider_status="IN_PROGRESS",
                          raw={"container_id": container})


def advance(token: str, ig_user_id: str, container: str, *, transport: Transport) -> PublishOutcome:
    """Check the container; publish it once ``FINISHED``."""
    ig_user_id = _user_id(ig_user_id)
    if not _SAFE_ID.match(str(container or "")):
        raise ClientError("instagram", "unknown Instagram container id")
    resp = transport.request("GET", f"{GRAPH}/{container}",
                             params={"fields": "status_code,status"}, headers=_auth(token))
    body = _raise_for(resp, "status check")
    status = str(body.get("status_code") or "IN_PROGRESS")
    if status in ("ERROR", "EXPIRED"):
        raise ClientError("instagram", f"Instagram could not process the video ({body.get('status') or status})")
    if status == "PUBLISHED":
        return PublishOutcome(status="published", ref=container, provider_status=status)
    if status != "FINISHED":
        return PublishOutcome(status="processing", ref=container, provider_status=status)
    pub = transport.request("POST", f"{GRAPH}/{ig_user_id}/media_publish",
                            params={"creation_id": container}, headers=_auth(token))
    media_id = str(_raise_for(pub, "publish").get("id") or "")
    if not _SAFE_ID.match(media_id):
        raise ClientError("instagram", "Instagram returned no media id", retryable=True)
    link = transport.request("GET", f"{GRAPH}/{media_id}", params={"fields": "permalink"}, headers=_auth(token))
    permalink = str(body_of(link).get("permalink") or "") if is_ok(link) else ""
    return PublishOutcome(status="published", ref=container, external_id=media_id, url=permalink,
                          provider_status="PUBLISHED", raw={"media_id": media_id})
