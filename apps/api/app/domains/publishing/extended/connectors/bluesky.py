"""Bluesky video post (AT Protocol XRPC against the account's PDS).

1. ``com.atproto.server.createSession`` with the handle/DID + app password.
2. ``com.atproto.repo.uploadBlob`` with the MP4 bytes -> a blob ref.
3. ``com.atproto.repo.createRecord`` of an ``app.bsky.feed.post`` whose embed is
   ``app.bsky.embed.video`` (the blob + aspect ratio). Hashtags get
   ``app.bsky.richtext.facet#tag`` facets (UTF-8 byte offsets) so they are
   clickable.

Image posts (Design Studio pages, up to 4) upload each image as a blob and
embed them with ``app.bsky.embed.images``; Bluesky caps an image blob at
about 1 MB, so the runner re-encodes larger pages as JPEG before upload.

Free: no developer app, no review, no API bill. The app password is stored
encrypted and only ever sent to the account's own PDS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .base import (
    STEP_PUBLISHED,
    PublishContext,
    PublishError,
    Step,
    Transport,
    fail,
    image_type,
    is_ok,
    json_of,
    register,
)

PLATFORM = "bluesky"
DEFAULT_PDS = "https://bsky.social"
MAX_IMAGES = 4
IMAGE_MAX_BYTES = 1_000_000
_TAG_RE = re.compile(r"(?<![\w#])#(\w{1,64})", re.UNICODE)


@dataclass(frozen=True)
class Session:
    access_jwt: str
    did: str
    handle: str
    pds: str


def pds_of(meta: dict | None) -> str:
    raw = str((meta or {}).get("pds") or "").strip().rstrip("/")
    return raw if raw.startswith("https://") else DEFAULT_PDS


def create_session(identifier: str, app_password: str, pds: str, *, transport: Transport) -> Session:
    """Log in with an app password. Raises :class:`PublishError` on refusal."""
    if not identifier or not app_password:
        raise PublishError(PLATFORM, "missing Bluesky handle or app password")
    resp = transport.request(
        "POST",
        f"{pds}/xrpc/com.atproto.server.createSession",
        headers={"Content-Type": "application/json"},
        json={"identifier": identifier, "password": app_password},
    )
    if not is_ok(resp):
        code = int(getattr(resp, "status_code", 0) or 0)
        if code in (400, 401):
            raise PublishError(PLATFORM, "Bluesky rejected the handle or app password. Create a new app password "
                                         "in Bluesky settings and reconnect.")
        raise fail(PLATFORM, "Bluesky login failed", resp=resp)
    body = json_of(resp)
    access = str(body.get("accessJwt") or "")
    did = str(body.get("did") or "")
    if not access or not did:
        raise PublishError(PLATFORM, "Bluesky login returned no session")
    return Session(access_jwt=access, did=did, handle=str(body.get("handle") or identifier), pds=pds)


def tag_facets(text: str) -> list[dict]:
    """``#tag`` facets with UTF-8 byte offsets, as the AT Protocol requires."""
    facets: list[dict] = []
    for match in _TAG_RE.finditer(text):
        start = len(text[: match.start()].encode("utf-8"))
        end = len(text[: match.end()].encode("utf-8"))
        facets.append({
            "index": {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": match.group(1)}],
        })
    return facets


def rkey_of(uri: str) -> str:
    return str(uri or "").rstrip("/").rsplit("/", 1)[-1]


def post_url(handle_or_did: str, uri: str) -> str:
    rkey = rkey_of(uri)
    return f"https://bsky.app/profile/{handle_or_did}/post/{rkey}" if rkey and handle_or_did else ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BlueskyConnector:
    platform = PLATFORM

    def _blob(self, session: Session, payload: bytes, content_type: str, what: str,
              transport: Transport) -> dict:
        up = transport.request(
            "POST",
            f"{session.pds}/xrpc/com.atproto.repo.uploadBlob",
            headers={"Authorization": f"Bearer {session.access_jwt}", "Content-Type": content_type},
            data=payload,
        )
        if not is_ok(up):
            raise fail(PLATFORM, f"uploading the {what} to Bluesky failed", resp=up)
        blob = json_of(up).get("blob")
        if not isinstance(blob, dict):
            raise PublishError(PLATFORM, f"Bluesky returned no blob for the {what}")
        return blob

    def _image_embed(self, ctx: PublishContext, session: Session, transport: Transport) -> dict:
        images = ctx.image_bytes()
        if not images:
            raise PublishError(PLATFORM, "Bluesky needs the image files to upload")
        if len(images) > MAX_IMAGES:
            raise PublishError(PLATFORM, f"Bluesky posts take at most {MAX_IMAGES} images")
        alt = (ctx.title or "Design")[:300]
        out = []
        for payload in images:
            if len(payload) > IMAGE_MAX_BYTES:
                raise PublishError(PLATFORM, "Bluesky accepts images up to 1 MB")
            content_type, _ext = image_type(payload)
            out.append({"alt": alt, "image": self._blob(session, payload, content_type, "image", transport)})
        return {"$type": "app.bsky.embed.images", "images": out}

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step:
        if not ctx.is_image_post and (not ctx.video_path or ctx.video_size() <= 0):
            raise PublishError(PLATFORM, "Bluesky needs the video file to upload")
        pds = pds_of(ctx.meta)
        session = create_session(ctx.external_account_id or str(ctx.meta.get("handle") or ""),
                                 ctx.access_token, pds, transport=transport)
        if ctx.is_image_post:
            embed = self._image_embed(ctx, session, transport)
        else:
            with open(ctx.video_path, "rb") as fh:
                payload = fh.read()
            embed = {
                "$type": "app.bsky.embed.video",
                "video": self._blob(session, payload, "video/mp4", "video", transport),
                "aspectRatio": {"width": 9, "height": 16},
            }

        record: dict = {
            "$type": "app.bsky.feed.post",
            "text": ctx.text,
            "createdAt": now_iso(),
            "embed": embed,
        }
        facets = tag_facets(ctx.text)
        if facets:
            record["facets"] = facets
        created = transport.request(
            "POST",
            f"{pds}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session.access_jwt}", "Content-Type": "application/json"},
            json={"repo": session.did, "collection": "app.bsky.feed.post", "record": record},
        )
        if not is_ok(created):
            raise fail(PLATFORM, "Bluesky refused the post", resp=created)
        uri = str(json_of(created).get("uri") or "")
        if not uri:
            raise PublishError(PLATFORM, "Bluesky created the post but returned no uri")
        return Step(status=STEP_PUBLISHED, external_id=uri, url=post_url(session.handle or session.did, uri),
                    progress={"uri": uri, "cid": str(json_of(created).get("cid") or "")})

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step:  # noqa: ARG002 - single step
        uri = str(ctx.progress.get("uri") or "")
        if not uri:
            raise PublishError(PLATFORM, "nothing to resume for Bluesky")
        return Step(status=STEP_PUBLISHED, external_id=uri, url=post_url(str(ctx.meta.get("handle") or ""), uri),
                    progress=dict(ctx.progress))


register(BlueskyConnector())
