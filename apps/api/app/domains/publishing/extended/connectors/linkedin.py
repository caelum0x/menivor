"""LinkedIn video post (Videos API + Posts API, versioned REST).

1. ``POST /rest/videos?action=initializeUpload`` with the owner urn and the
   file size -> upload instructions (byte ranges + URLs), the video urn and an
   upload token.
2. ``PUT`` each byte range to its upload URL; LinkedIn returns an ``ETag`` per part.
3. ``POST /rest/videos?action=finalizeUpload`` with the part ETags.
4. ``GET /rest/videos/{urn}`` until ``status`` is ``AVAILABLE``.
5. ``POST /rest/posts`` with the commentary and ``content.media.id`` = video urn.
   The new post urn comes back in the ``x-restli-id`` header.

Image posts (Design Studio pages) use the Images API: per page
``POST /rest/images?action=initializeUpload`` -> an ``uploadUrl`` and an image
urn, ``PUT`` the bytes, then one ``POST /rest/posts`` with ``content.media``
(one page) or ``content.multiImage`` (2-20 pages).

The owner is the member (``urn:li:person:{id}``) or a company page
(``urn:li:organization:{id}``, Community Management API only).
Commentary uses LinkedIn's "little text" format, so reserved characters are
escaped and hashtags are written as ``{hashtag|\\#|tag}``.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .base import (
    STEP_PROCESSING,
    STEP_PUBLISHED,
    PublishContext,
    PublishError,
    Step,
    Transport,
    fail,
    is_ok,
    json_of,
    read_range,
    register,
)

PLATFORM = "linkedin"
API = "https://api.linkedin.com/rest"
LINKEDIN_VERSION = "202409"
MAX_IMAGES = 20

_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")
_TAG_IN_TEXT = re.compile(r"(?<![\w#])#(\w{1,100})", re.UNICODE)


def headers(token: str, *, json_body: bool = True) -> dict:
    out = {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if json_body:
        out["Content-Type"] = "application/json"
    return out


def little_text(text: str) -> str:
    """Escape LinkedIn reserved characters; keep ``#tags`` as hashtag templates."""
    tags: list[str] = []

    def _stash(match: re.Match) -> str:
        tags.append(match.group(1))
        return f"\x00{len(tags) - 1}\x00"

    stashed = _TAG_IN_TEXT.sub(_stash, str(text or ""))
    escaped = _RESERVED.sub(r"\\\1", stashed)
    return re.sub(r"\x00(\d+)\x00", lambda m: "{hashtag|\\#|" + tags[int(m.group(1))] + "}", escaped)


def owner_urn(ctx: PublishContext) -> str:
    target = str(ctx.target_id or "").strip()
    if target.startswith("urn:li:"):
        return target
    member = str(ctx.meta.get("member_urn") or "").strip()
    if member:
        return member
    if ctx.external_account_id:
        return f"urn:li:person:{ctx.external_account_id}"
    return ""


def post_url(post_urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else ""


class LinkedInConnector:
    platform = PLATFORM

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step:
        if not ctx.access_token:
            raise PublishError(PLATFORM, "missing LinkedIn access token")
        owner = owner_urn(ctx)
        if not owner:
            raise PublishError(PLATFORM, "could not tell which LinkedIn member or page to post as")
        if ctx.is_image_post:
            return self._publish_images(ctx, owner, transport)
        size = ctx.video_size()
        if not ctx.video_path or size <= 0:
            raise PublishError(PLATFORM, "LinkedIn needs the video file to upload")

        init = transport.request(
            "POST",
            f"{API}/videos?action=initializeUpload",
            headers=headers(ctx.access_token),
            json={"initializeUploadRequest": {
                "owner": owner, "fileSizeBytes": size, "uploadCaptions": False, "uploadThumbnail": False,
            }},
        )
        if not is_ok(init):
            raise fail(PLATFORM, "LinkedIn refused the video upload", resp=init)
        value = json_of(init).get("value") or {}
        video_urn = str(value.get("video") or "")
        upload_token = str(value.get("uploadToken") or "")
        instructions = value.get("uploadInstructions") or []
        if not video_urn or not instructions:
            raise PublishError(PLATFORM, "LinkedIn returned no upload instructions")

        etags: list[str] = []
        for part in instructions:
            first = int(part.get("firstByte") or 0)
            last = int(part.get("lastByte") or (size - 1))
            put = transport.request(
                "PUT",
                str(part.get("uploadUrl") or ""),
                headers={"Authorization": f"Bearer {ctx.access_token}", "Content-Type": "application/octet-stream"},
                data=read_range(ctx.video_path, first, last),
            )
            if not is_ok(put):
                raise fail(PLATFORM, "uploading the video to LinkedIn failed", resp=put)
            hdrs = getattr(put, "headers", {}) or {}
            etag = str(hdrs.get("ETag") or hdrs.get("etag") or "").strip()
            if not etag:
                raise PublishError(PLATFORM, "LinkedIn did not confirm an uploaded part")
            etags.append(etag)

        fin = transport.request(
            "POST",
            f"{API}/videos?action=finalizeUpload",
            headers=headers(ctx.access_token),
            json={"finalizeUploadRequest": {
                "video": video_urn, "uploadToken": upload_token, "uploadedPartIds": etags,
            }},
        )
        if not is_ok(fin):
            raise fail(PLATFORM, "LinkedIn could not finish the upload", resp=fin)
        return self._advance(ctx, {"video_urn": video_urn, "owner": owner}, transport)

    def _upload_image(self, ctx: PublishContext, owner: str, payload: bytes, transport: Transport) -> str:
        init = transport.request(
            "POST", f"{API}/images?action=initializeUpload", headers=headers(ctx.access_token),
            json={"initializeUploadRequest": {"owner": owner}},
        )
        if not is_ok(init):
            raise fail(PLATFORM, "LinkedIn refused the image upload", resp=init)
        value = json_of(init).get("value") or {}
        upload_url = str(value.get("uploadUrl") or "")
        image_urn = str(value.get("image") or "")
        if not upload_url or not image_urn:
            raise PublishError(PLATFORM, "LinkedIn returned no image upload URL")
        put = transport.request(
            "PUT", upload_url,
            headers={"Authorization": f"Bearer {ctx.access_token}", "Content-Type": "application/octet-stream"},
            data=payload,
        )
        if not is_ok(put):
            raise fail(PLATFORM, "uploading the image to LinkedIn failed", resp=put)
        return image_urn

    def _publish_images(self, ctx: PublishContext, owner: str, transport: Transport) -> Step:
        images = ctx.image_bytes()
        if not images:
            raise PublishError(PLATFORM, "LinkedIn needs the image files to upload")
        if len(images) > MAX_IMAGES:
            raise PublishError(PLATFORM, f"LinkedIn posts take at most {MAX_IMAGES} images")
        urns = [self._upload_image(ctx, owner, payload, transport) for payload in images]
        alt = (ctx.title or "Image")[:120]
        if len(urns) == 1:
            content: dict = {"media": {"title": alt, "id": urns[0], "altText": alt}}
        else:
            content = {"multiImage": {"images": [{"id": urn, "altText": alt} for urn in urns]}}
        body = {
            "author": owner,
            "commentary": little_text(ctx.text),
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "content": content,
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        post = transport.request("POST", f"{API}/posts", headers=headers(ctx.access_token), json=body)
        if not is_ok(post):
            raise fail(PLATFORM, "LinkedIn refused the image post", resp=post)
        hdrs = getattr(post, "headers", {}) or {}
        post_urn = str(hdrs.get("x-restli-id") or hdrs.get("X-RestLi-Id") or json_of(post).get("id") or "")
        return Step(status=STEP_PUBLISHED, external_id=post_urn or urns[0], url=post_url(post_urn),
                    progress={"image_urns": urns, "owner": owner, "post_urn": post_urn})

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step:
        progress = dict(ctx.progress or {})
        if progress.get("post_urn"):
            urn = str(progress["post_urn"])
            return Step(status=STEP_PUBLISHED, external_id=urn, url=post_url(urn), progress=progress)
        if not progress.get("video_urn"):
            raise PublishError(PLATFORM, "missing LinkedIn video to continue")
        if not ctx.access_token:
            raise PublishError(PLATFORM, "missing LinkedIn access token")
        return self._advance(ctx, progress, transport)

    def _advance(self, ctx: PublishContext, progress: dict, transport: Transport) -> Step:
        video_urn = progress["video_urn"]
        resp = transport.request(
            "GET", f"{API}/videos/{quote(video_urn, safe='')}", headers=headers(ctx.access_token, json_body=False)
        )
        status = str(json_of(resp).get("status") or "").upper() if is_ok(resp) else ""
        if status in ("PROCESSING_FAILED", "FAILED"):
            raise PublishError(PLATFORM, "LinkedIn could not process the video")
        if status != "AVAILABLE":
            return Step(status=STEP_PROCESSING, external_id=video_urn, progress=progress,
                        note="LinkedIn is processing the video.")

        body = {
            "author": progress.get("owner") or owner_urn(ctx),
            "commentary": little_text(ctx.text),
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "content": {"media": {"title": ctx.title or "Video", "id": video_urn}},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        post = transport.request("POST", f"{API}/posts", headers=headers(ctx.access_token), json=body)
        if not is_ok(post):
            raise fail(PLATFORM, "LinkedIn refused the post", resp=post)
        hdrs = getattr(post, "headers", {}) or {}
        post_urn = str(hdrs.get("x-restli-id") or hdrs.get("X-RestLi-Id") or json_of(post).get("id") or "")
        return Step(status=STEP_PUBLISHED, external_id=post_urn or video_urn, url=post_url(post_urn),
                    progress={**progress, "post_urn": post_urn})


register(LinkedInConnector())
