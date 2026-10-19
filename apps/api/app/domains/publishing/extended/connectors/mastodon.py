"""Mastodon status post (any instance; free, no review).

The creator creates an application under *Preferences -> Development* on
their own instance (scopes ``read write``) and pastes the instance URL plus
the application's access token. Posting:

1. ``POST /api/v2/media`` (multipart) - ``200`` when the video is ready,
   ``202`` while the instance transcodes it;
2. while ``202``: ``GET /api/v1/media/:id`` until it returns ``200``
   (``206`` = still processing) - reported as a ``processing`` step so the
   due-runner polls it instead of blocking a worker;
   Image posts (Design Studio pages) upload up to 4 images the same way;
3. ``POST /api/v1/statuses`` with ``media_ids`` and an ``Idempotency-Key`` so a
   retried request can never double-post.

The instance URL is user-supplied, so it is restricted to a bare public
``https://host`` (no path, credentials, private or internal addresses).
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from .base import (
    STEP_PROCESSING,
    STEP_PUBLISHED,
    PublishContext,
    PublishError,
    Step,
    Transport,
    error_text,
    image_type,
    is_ok,
    json_of,
    multipart_body,
    register,
    retryable,
    status_of,
)

PLATFORM = "mastodon"
VISIBILITIES = ("public", "unlisted", "private")
MAX_IMAGES = 4
_BLOCKED_HOSTS = frozenset({"localhost", "metadata", "metadata.google.internal", "instance-data"})
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")


def _default_resolver(url: str) -> bool:
    """True when ``url``'s host resolves only to public addresses (shared SSRF classifier)."""
    try:
        from app.services import webhooks

        error, pinned = webhooks._validate_and_resolve(url)  # noqa: SLF001 - shared SSRF guard
        return error is None and bool(pinned) and not webhooks._ip_is_internal(pinned)  # noqa: SLF001
    except Exception:  # noqa: BLE001 - unresolvable reads as unsafe
        return False


def normalize_instance(raw: str, *, resolve: Callable[[str], bool] | None = _default_resolver) -> str:
    """``"mastodon.social"`` / ``"https://mastodon.social/"`` -> ``"https://mastodon.social"``.

    Raises :class:`PublishError` for anything that is not a public https host.
    ``resolve=None`` skips the DNS check (unit tests only).
    """
    value = str(raw or "").strip()
    if not value or len(value) > 253 + 8:
        raise PublishError(PLATFORM, "Enter your Mastodon instance, for example mastodon.social.")
    if "://" not in value:
        value = f"https://{value}"
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise PublishError(PLATFORM, "That instance address is not valid.") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https":
        raise PublishError(PLATFORM, "The instance must use https.")
    if parsed.username or parsed.password or port not in (None, 443):
        raise PublishError(PLATFORM, "Enter just the instance address, without a port or login.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise PublishError(PLATFORM, "Enter just the instance address, without a path.")
    try:
        ipaddress.ip_address(host.strip("[]"))
        is_ip = True
    except ValueError:
        is_ip = False
    if is_ip or host in _BLOCKED_HOSTS or host.endswith((".internal", ".local", ".localhost")) \
            or not _HOST_RE.match(host):
        raise PublishError(PLATFORM, "The instance must be a public domain name.")
    url = f"https://{host}"
    if resolve is not None and not resolve(url):
        raise PublishError(PLATFORM, "That instance does not resolve to a public server.")
    return url


def _request(transport: Transport, method: str, url: str, **kwargs: Any):
    try:
        return transport.request(method, url, **kwargs)
    except Exception:  # noqa: BLE001 - network failure; retried by the runner
        raise PublishError(PLATFORM, "the Mastodon instance could not be reached", retryable=True) from None


def _auth(token: str, **extra: str) -> dict:
    return {"Authorization": f"Bearer {token}", **extra}


def _raise_for(resp: Any, action: str) -> None:
    code = status_of(resp)
    if code == 401:
        raise PublishError(PLATFORM, "Mastodon rejected the access token. Create a new one and reconnect.")
    if code == 403:
        raise PublishError(PLATFORM, f"The access token is missing the 'write' scope needed to {action}.")
    raise PublishError(PLATFORM, f"Mastodon refused to {action}: {error_text(resp)}", retryable=retryable(resp))


@dataclass(frozen=True)
class Account:
    id: str
    username: str
    acct: str
    url: str
    max_characters: int


def verify(instance_url: str, token: str, *, transport: Transport) -> Account:
    if not token or len(token) < 20:
        raise PublishError(PLATFORM, "Paste the access token from Preferences -> Development on your instance.")
    resp = _request(transport, "GET", f"{instance_url}/api/v1/accounts/verify_credentials", headers=_auth(token))
    if not is_ok(resp):
        _raise_for(resp, "read the account")
    body = json_of(resp)
    max_chars = 500
    info = _request(transport, "GET", f"{instance_url}/api/v2/instance")
    if is_ok(info):
        conf = json_of(info).get("configuration") or {}
        try:
            max_chars = int(((conf.get("statuses") or {}).get("max_characters")) or 500)
        except (TypeError, ValueError):
            max_chars = 500
    return Account(
        id=str(body.get("id") or ""),
        username=str(body.get("username") or ""),
        acct=str(body.get("acct") or body.get("username") or ""),
        url=str(body.get("url") or ""),
        max_characters=max(1, max_chars),
    )


def strip_html(value: str) -> str:
    """Mastodon returns status content as HTML; turn it into plain text."""
    text = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.I)
    text = re.sub(r"</p>\s*<p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def idempotency_key(ctx: PublishContext, media_ids: list[str] | None = None) -> str:
    media = ",".join(media_ids) if media_ids is not None else str(ctx.progress.get("media_id") or "")
    seed = f"{ctx.target_id}|{ctx.meta.get('post_id') or ''}|{ctx.text}|{media}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:48]


class MastodonConnector:
    platform = PLATFORM

    def _instance(self, ctx: PublishContext) -> str:
        instance = str(ctx.meta.get("instance_url") or "")
        if not instance.startswith("https://"):
            raise PublishError(PLATFORM, "the Mastodon instance is not set; reconnect the account")
        return instance

    def _status(self, ctx: PublishContext, instance: str, media_id: str, transport: Transport,
                media_ids: list[str] | None = None) -> Step:
        visibility = str(ctx.meta.get("visibility") or "public")
        body: dict = {"status": ctx.text, "visibility": visibility if visibility in VISIBILITIES else "public"}
        ids = list(media_ids) if media_ids is not None else ([media_id] if media_id else [])
        if ids:
            body["media_ids"] = ids
        key = idempotency_key(ctx, ids) if media_ids is not None else idempotency_key(ctx)
        resp = _request(transport, "POST", f"{instance}/api/v1/statuses",
                        headers=_auth(ctx.access_token, **{"Content-Type": "application/json",
                                                           "Idempotency-Key": key}),
                        json=body)
        if not is_ok(resp):
            _raise_for(resp, "post")
        status = json_of(resp)
        status_id = str(status.get("id") or "")
        if not status_id:
            raise PublishError(PLATFORM, "Mastodon accepted the post but returned no id")
        progress = {"media_id": media_id, "status_id": status_id}
        if media_ids is not None:
            progress["media_ids"] = ids
        return Step(status=STEP_PUBLISHED, external_id=status_id, url=str(status.get("url") or ""),
                    progress=progress)

    def _publish_images(self, ctx: PublishContext, instance: str, transport: Transport) -> Step:
        images = ctx.image_bytes()
        if not images:
            raise PublishError(PLATFORM, "Mastodon needs the image files to upload")
        if len(images) > MAX_IMAGES:
            raise PublishError(PLATFORM, f"Mastodon posts take at most {MAX_IMAGES} images")
        media_ids: list[str] = []
        pending = False
        for index, payload in enumerate(images):
            content_type, ext = image_type(payload)
            body, form_type = multipart_body({"description": (ctx.title or "Design")[:1500]}, "file",
                                             f"design-{index + 1}.{ext}", payload, content_type=content_type)
            resp = _request(transport, "POST", f"{instance}/api/v2/media",
                            headers=_auth(ctx.access_token, **{"Content-Type": form_type}), data=body)
            if status_of(resp) == 413:
                raise PublishError(PLATFORM, "An image is larger than this instance accepts.")
            if status_of(resp) not in (200, 202):
                _raise_for(resp, "upload the image")
            media_id = str(json_of(resp).get("id") or "")
            if not media_id:
                raise PublishError(PLATFORM, "Mastodon accepted the upload but returned no media id")
            media_ids.append(media_id)
            pending = pending or status_of(resp) == 202 or not json_of(resp).get("url")
        if pending:
            return Step(status=STEP_PROCESSING, progress={"media_ids": media_ids},
                        note="Mastodon is processing the images.")
        return self._status(ctx, instance, "", transport, media_ids=media_ids)

    def _resume_images(self, ctx: PublishContext, instance: str, media_ids: list[str], transport: Transport) -> Step:
        for media_id in media_ids:
            resp = _request(transport, "GET", f"{instance}/api/v1/media/{media_id}", headers=_auth(ctx.access_token))
            if status_of(resp) == 206 or (is_ok(resp) and not json_of(resp).get("url")):
                return Step(status=STEP_PROCESSING, progress={"media_ids": media_ids},
                            note="Mastodon is processing the images.")
            if not is_ok(resp):
                _raise_for(resp, "check the image")
        return self._status(ctx, instance, "", transport, media_ids=media_ids)

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step:
        instance = self._instance(ctx)
        if ctx.is_image_post:
            return self._publish_images(ctx, instance, transport)
        if not (ctx.video_path and ctx.video_size() > 0):
            if not (ctx.text or "").strip():
                raise PublishError(PLATFORM, "nothing to post: add text or a video")
            return self._status(ctx, instance, "", transport)
        with open(ctx.video_path, "rb") as fh:
            payload = fh.read()
        body, content_type = multipart_body({}, "file", "reel.mp4", payload)
        resp = _request(transport, "POST", f"{instance}/api/v2/media",
                        headers=_auth(ctx.access_token, **{"Content-Type": content_type}), data=body)
        if status_of(resp) == 413:
            raise PublishError(PLATFORM, "The video is larger than this instance accepts.")
        if status_of(resp) not in (200, 202):
            _raise_for(resp, "upload the video")
        media_id = str(json_of(resp).get("id") or "")
        if not media_id:
            raise PublishError(PLATFORM, "Mastodon accepted the upload but returned no media id")
        if status_of(resp) == 202 or not json_of(resp).get("url"):
            return Step(status=STEP_PROCESSING, progress={"media_id": media_id},
                        note="Mastodon is processing the video.")
        return self._status(ctx, instance, media_id, transport)

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step:
        if ctx.progress.get("status_id"):
            return Step(status=STEP_PUBLISHED, external_id=str(ctx.progress["status_id"]),
                        progress=dict(ctx.progress))
        media_ids = [str(m) for m in (ctx.progress.get("media_ids") or []) if m]
        if media_ids:
            return self._resume_images(ctx, self._instance(ctx), media_ids, transport)
        media_id = str(ctx.progress.get("media_id") or "")
        if not media_id:
            raise PublishError(PLATFORM, "nothing to resume for Mastodon")
        instance = self._instance(ctx)
        resp = _request(transport, "GET", f"{instance}/api/v1/media/{media_id}", headers=_auth(ctx.access_token))
        if status_of(resp) == 206 or (is_ok(resp) and not json_of(resp).get("url")):
            return Step(status=STEP_PROCESSING, progress={"media_id": media_id},
                        note="Mastodon is processing the video.")
        if not is_ok(resp):
            _raise_for(resp, "check the video")
        return self._status(ctx, instance, media_id, transport)


register(MastodonConnector())
