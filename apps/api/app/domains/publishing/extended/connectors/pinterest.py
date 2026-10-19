"""Pinterest video Pin (API v5).

1. ``POST /v5/media`` (``media_type=video``) -> ``media_id``, ``upload_url`` and
   the signed ``upload_parameters``.
2. ``POST`` the file as multipart to ``upload_url`` with those parameters.
3. ``GET /v5/media/{media_id}`` until ``status`` is ``succeeded``.
4. ``POST /v5/pins`` on the chosen board with
   ``media_source = {source_type: video_id, media_id, cover_image_key_frame_time}``.

Image Pins (Design Studio pages) are one call: ``POST /v5/pins`` with
``media_source = {source_type: image_url, url}`` for one page or
``{source_type: multiple_image_urls, items: [{url}, ...]}`` for a carousel Pin
(2-5 images). Pinterest fetches the images itself from the public URLs.

Pinterest apps on Trial access may only create Pins visible to the app owner;
the operator can point ``pinterest_api_base`` at the sandbox host for that.
"""

from __future__ import annotations

from ..catalog import pinterest_api_base
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
    multipart_body,
    register,
)

PLATFORM = "pinterest"
COVER_FRAME_SECONDS = 1
MAX_CAROUSEL = 5


def _auth(token: str, *, json_body: bool = True) -> dict:
    out = {"Authorization": f"Bearer {token}"}
    if json_body:
        out["Content-Type"] = "application/json"
    return out


class PinterestConnector:
    platform = PLATFORM

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step:
        if not ctx.access_token:
            raise PublishError(PLATFORM, "missing Pinterest access token")
        if not ctx.target_id:
            raise PublishError(PLATFORM, "choose a Pinterest board under Connections")
        if ctx.is_image_post:
            return self._publish_images(ctx, transport)
        if not ctx.video_path or ctx.video_size() <= 0:
            raise PublishError(PLATFORM, "Pinterest needs the video file to upload")
        base = pinterest_api_base()

        reg = transport.request("POST", f"{base}/v5/media", headers=_auth(ctx.access_token),
                                json={"media_type": "video"})
        if not is_ok(reg):
            raise fail(PLATFORM, "Pinterest refused the video upload", resp=reg)
        body = json_of(reg)
        media_id = str(body.get("media_id") or "")
        upload_url = str(body.get("upload_url") or "")
        params = body.get("upload_parameters") or {}
        if not media_id or not upload_url:
            raise PublishError(PLATFORM, "Pinterest returned no upload URL")

        with open(ctx.video_path, "rb") as fh:
            payload = fh.read()
        form, content_type = multipart_body({str(k): str(v) for k, v in params.items()}, "file", "reel.mp4", payload)
        up = transport.request("POST", upload_url, headers={"Content-Type": content_type}, data=form)
        if not is_ok(up):
            raise fail(PLATFORM, "uploading the video to Pinterest failed", resp=up)
        return self._advance(ctx, {"media_id": media_id, "board_id": ctx.target_id}, transport)

    def _publish_images(self, ctx: PublishContext, transport: Transport) -> Step:
        urls = list(ctx.image_urls)
        if not urls:
            raise PublishError(PLATFORM, "Pinterest needs public image URLs to fetch the design")
        if len(urls) > MAX_CAROUSEL:
            raise PublishError(PLATFORM, f"Pinterest carousel Pins take at most {MAX_CAROUSEL} images")
        if len(urls) == 1:
            source: dict = {"source_type": "image_url", "url": urls[0]}
        else:
            source = {"source_type": "multiple_image_urls", "items": [{"url": url} for url in urls]}
        pin = transport.request(
            "POST", f"{pinterest_api_base()}/v5/pins", headers=_auth(ctx.access_token),
            json={"board_id": ctx.target_id, "title": ctx.title, "description": ctx.text, "media_source": source},
        )
        if not is_ok(pin):
            raise fail(PLATFORM, "Pinterest refused the image Pin", resp=pin)
        pin_id = str(json_of(pin).get("id") or "")
        if not pin_id:
            raise PublishError(PLATFORM, "Pinterest created the Pin but returned no id")
        return Step(status=STEP_PUBLISHED, external_id=pin_id, url=f"https://www.pinterest.com/pin/{pin_id}/",
                    progress={"pin_id": pin_id, "board_id": ctx.target_id})

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step:
        progress = dict(ctx.progress or {})
        if progress.get("pin_id"):
            pin_id = str(progress["pin_id"])
            return Step(status=STEP_PUBLISHED, external_id=pin_id, url=f"https://www.pinterest.com/pin/{pin_id}/",
                        progress=progress)
        if not progress.get("media_id"):
            raise PublishError(PLATFORM, "missing Pinterest media id to continue")
        return self._advance(ctx, progress, transport)

    def _advance(self, ctx: PublishContext, progress: dict, transport: Transport) -> Step:
        base = pinterest_api_base()
        media_id = progress["media_id"]
        resp = transport.request("GET", f"{base}/v5/media/{media_id}", headers=_auth(ctx.access_token, json_body=False))
        status = str(json_of(resp).get("status") or "").lower() if is_ok(resp) else ""
        if status == "failed":
            raise PublishError(PLATFORM, "Pinterest could not process the video")
        if status != "succeeded":
            return Step(status=STEP_PROCESSING, external_id=media_id, progress=progress,
                        note="Pinterest is processing the video.")
        pin = transport.request(
            "POST",
            f"{base}/v5/pins",
            headers=_auth(ctx.access_token),
            json={
                "board_id": progress.get("board_id") or ctx.target_id,
                "title": ctx.title,
                "description": ctx.text,
                "media_source": {
                    "source_type": "video_id",
                    "media_id": media_id,
                    "cover_image_key_frame_time": COVER_FRAME_SECONDS,
                },
            },
        )
        if not is_ok(pin):
            raise fail(PLATFORM, "Pinterest refused the Pin", resp=pin)
        pin_id = str(json_of(pin).get("id") or "")
        if not pin_id:
            raise PublishError(PLATFORM, "Pinterest created the Pin but returned no id")
        return Step(status=STEP_PUBLISHED, external_id=pin_id, url=f"https://www.pinterest.com/pin/{pin_id}/",
                    progress={**progress, "pin_id": pin_id})


register(PinterestConnector())
