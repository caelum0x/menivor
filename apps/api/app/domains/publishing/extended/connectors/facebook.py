"""Facebook Pages video publish (Graph API).

1. ``POST https://graph-video.facebook.com/v21.0/{page-id}/videos`` with the
   Page access token, ``file_url`` (a short-lived public URL of the MP4),
   ``description`` and ``title``. Facebook fetches the file itself.
2. ``GET /{video-id}?fields=status,permalink_url`` until
   ``status.video_status`` is ``ready`` (``processing`` / ``upload`` keep
   waiting; ``error`` fails).

Image posts (Design Studio pages) are a single step:

* one image: ``POST /{page-id}/photos`` with ``url`` + ``message``;
* several: each page is uploaded unpublished (``published=false``), then one
  ``POST /{page-id}/feed`` attaches them all (``attached_media``).
"""

from __future__ import annotations

import json as _json

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
    register,
)

PLATFORM = "facebook"
GRAPH = "https://graph.facebook.com/v21.0"
GRAPH_VIDEO = "https://graph-video.facebook.com/v21.0"
MAX_IMAGES = 10


def _permalink(raw: str, video_id: str) -> str:
    link = str(raw or "").strip()
    if link.startswith("/"):
        return f"https://www.facebook.com{link}"
    return link or f"https://www.facebook.com/watch/?v={video_id}"


class FacebookConnector:
    platform = PLATFORM

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step:
        token = ctx.target_token or ""
        if not token or not ctx.target_id:
            raise PublishError(PLATFORM, "choose which Facebook Page to post to under Connections")
        if ctx.is_image_post:
            return self._publish_images(ctx, token, transport)
        if not ctx.video_url:
            raise PublishError(PLATFORM, "Facebook needs a public video URL to fetch the reel")
        resp = transport.request(
            "POST",
            f"{GRAPH_VIDEO}/{ctx.target_id}/videos",
            data={
                "file_url": ctx.video_url,
                "description": ctx.text,
                "title": ctx.title,
                "published": "true",
                "access_token": token,
            },
        )
        if not is_ok(resp):
            raise fail(PLATFORM, "Facebook refused the video", resp=resp)
        video_id = str(json_of(resp).get("id") or "")
        if not video_id:
            raise PublishError(PLATFORM, "Facebook accepted the video but returned no id")
        return self._check(ctx, video_id, transport)

    def _publish_images(self, ctx: PublishContext, token: str, transport: Transport) -> Step:
        urls = list(ctx.image_urls)
        if not urls:
            raise PublishError(PLATFORM, "Facebook needs public image URLs to fetch the design")
        if len(urls) > MAX_IMAGES:
            raise PublishError(PLATFORM, f"Facebook posts take at most {MAX_IMAGES} images")
        if len(urls) == 1:
            resp = transport.request(
                "POST", f"{GRAPH}/{ctx.target_id}/photos",
                data={"url": urls[0], "message": ctx.text, "published": "true", "access_token": token},
            )
            if not is_ok(resp):
                raise fail(PLATFORM, "Facebook refused the image", resp=resp)
            body = json_of(resp)
            post_id = str(body.get("post_id") or body.get("id") or "")
            if not post_id:
                raise PublishError(PLATFORM, "Facebook accepted the image but returned no id")
            return Step(status=STEP_PUBLISHED, external_id=post_id, url=f"https://www.facebook.com/{post_id}",
                        progress={"post_id": post_id})
        photo_ids: list[str] = []
        for url in urls:
            resp = transport.request(
                "POST", f"{GRAPH}/{ctx.target_id}/photos",
                data={"url": url, "published": "false", "access_token": token},
            )
            if not is_ok(resp):
                raise fail(PLATFORM, "Facebook refused one of the images", resp=resp)
            photo_id = str(json_of(resp).get("id") or "")
            if not photo_id:
                raise PublishError(PLATFORM, "Facebook accepted an image but returned no id")
            photo_ids.append(photo_id)
        data = {"message": ctx.text, "access_token": token}
        for index, photo_id in enumerate(photo_ids):
            data[f"attached_media[{index}]"] = _json.dumps({"media_fbid": photo_id})
        feed = transport.request("POST", f"{GRAPH}/{ctx.target_id}/feed", data=data)
        if not is_ok(feed):
            raise fail(PLATFORM, "Facebook refused the multi-image post", resp=feed)
        post_id = str(json_of(feed).get("id") or "")
        if not post_id:
            raise PublishError(PLATFORM, "Facebook created the post but returned no id")
        return Step(status=STEP_PUBLISHED, external_id=post_id, url=f"https://www.facebook.com/{post_id}",
                    progress={"post_id": post_id, "photo_ids": photo_ids})

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step:
        if ctx.progress.get("post_id") and not ctx.progress.get("video_id"):
            post_id = str(ctx.progress["post_id"])
            return Step(status=STEP_PUBLISHED, external_id=post_id, url=f"https://www.facebook.com/{post_id}",
                        progress=dict(ctx.progress))
        video_id = str(ctx.progress.get("video_id") or "")
        if not video_id:
            raise PublishError(PLATFORM, "missing Facebook video id to check")
        return self._check(ctx, video_id, transport)

    def _check(self, ctx: PublishContext, video_id: str, transport: Transport) -> Step:
        resp = transport.request(
            "GET",
            f"{GRAPH}/{video_id}",
            params={"fields": "status,permalink_url", "access_token": ctx.target_token},
        )
        progress = {"video_id": video_id}
        if not is_ok(resp):
            # The video was accepted; a failed status read just means "check again".
            return Step(status=STEP_PROCESSING, external_id=video_id, progress=progress)
        body = json_of(resp)
        status = body.get("status") if isinstance(body.get("status"), dict) else {}
        state = str(status.get("video_status") or "").lower()
        if state == "error":
            raise PublishError(PLATFORM, "Facebook could not process the video")
        url = _permalink(body.get("permalink_url"), video_id)
        if state in ("ready", ""):
            return Step(status=STEP_PUBLISHED, external_id=video_id, url=url, progress=progress)
        return Step(status=STEP_PROCESSING, external_id=video_id, url=url, progress=progress,
                    note=f"Facebook is processing the video ({state}).")


register(FacebookConnector())
