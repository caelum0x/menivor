"""X (API v2) video post: chunked media upload, then create the post.

1. ``POST /2/media/upload/initialize`` (``media_type=video/mp4``,
   ``media_category=tweet_video``, ``total_bytes``) -> media id.
2. ``POST /2/media/upload/{id}/append`` - multipart chunks with ``segment_index``.
3. ``POST /2/media/upload/{id}/finalize`` -> ``processing_info``.
4. ``GET /2/media/upload?command=STATUS&media_id=`` until ``succeeded``.
5. ``POST /2/tweets`` with ``text`` and ``media.media_ids``.

Image posts (Design Studio pages, up to 4): each image is one
``POST /2/media/upload`` (multipart ``media`` + ``media_category=tweet_image``),
then ``POST /2/tweets`` with all the media ids. Images need no processing wait.

All calls use the creator's OAuth 2.0 user token (``media.write`` +
``tweet.write``). X bills API usage to the Menivor developer account, which is
why the service only runs this when the operator has declared a paid plan.
"""

from __future__ import annotations

from .base import (
    STEP_PROCESSING,
    STEP_PUBLISHED,
    PublishContext,
    PublishError,
    Step,
    Transport,
    fail,
    image_type,
    is_ok,
    json_of,
    multipart_body,
    read_chunks,
    register,
)

PLATFORM = "x"
API = "https://api.x.com/2"
CHUNK_BYTES = 4 * 1024 * 1024
MAX_IMAGES = 4
IMAGE_MAX_BYTES = 5 * 1024 * 1024


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class XConnector:
    platform = PLATFORM

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step:
        if not ctx.access_token:
            raise PublishError(PLATFORM, "missing X access token")
        if ctx.is_image_post:
            return self._publish_images(ctx, transport)
        size = ctx.video_size()
        if not ctx.video_path or size <= 0:
            raise PublishError(PLATFORM, "X needs the video file to upload")

        init = transport.request(
            "POST",
            f"{API}/media/upload/initialize",
            headers={**_auth(ctx.access_token), "Content-Type": "application/json"},
            json={"media_type": "video/mp4", "total_bytes": size, "media_category": "tweet_video"},
        )
        if not is_ok(init):
            raise fail(PLATFORM, "X refused the video upload", resp=init)
        media_id = str((json_of(init).get("data") or {}).get("id") or "")
        if not media_id:
            raise PublishError(PLATFORM, "X returned no media id")

        for index, chunk in read_chunks(ctx.video_path, CHUNK_BYTES):
            body, content_type = multipart_body({"segment_index": str(index)}, "media", "reel.mp4", chunk)
            part = transport.request(
                "POST",
                f"{API}/media/upload/{media_id}/append",
                headers={**_auth(ctx.access_token), "Content-Type": content_type},
                data=body,
            )
            if not is_ok(part):
                raise fail(PLATFORM, "uploading the video to X failed", resp=part)

        fin = transport.request(
            "POST", f"{API}/media/upload/{media_id}/finalize", headers=_auth(ctx.access_token)
        )
        if not is_ok(fin):
            raise fail(PLATFORM, "X could not finish the upload", resp=fin)
        info = (json_of(fin).get("data") or {}).get("processing_info") or {}
        progress = {"media_id": media_id}
        state = str(info.get("state") or "succeeded").lower()
        if state == "failed":
            raise PublishError(PLATFORM, "X could not process the video")
        if state != "succeeded":
            return Step(status=STEP_PROCESSING, external_id=media_id, progress=progress,
                        note="X is processing the video.")
        return self._post(ctx, progress, transport)

    def _publish_images(self, ctx: PublishContext, transport: Transport) -> Step:
        images = ctx.image_bytes()
        if not images:
            raise PublishError(PLATFORM, "X needs the image files to upload")
        if len(images) > MAX_IMAGES:
            raise PublishError(PLATFORM, f"X posts take at most {MAX_IMAGES} images")
        media_ids: list[str] = []
        for index, payload in enumerate(images):
            if len(payload) > IMAGE_MAX_BYTES:
                raise PublishError(PLATFORM, "X accepts images up to 5 MB")
            content_type, ext = image_type(payload)
            body, form_type = multipart_body({"media_category": "tweet_image", "media_type": content_type},
                                             "media", f"page{index + 1}.{ext}", payload, content_type=content_type)
            resp = transport.request("POST", f"{API}/media/upload",
                                     headers={**_auth(ctx.access_token), "Content-Type": form_type}, data=body)
            if not is_ok(resp):
                raise fail(PLATFORM, "uploading the image to X failed", resp=resp)
            media_id = str((json_of(resp).get("data") or {}).get("id") or "")
            if not media_id:
                raise PublishError(PLATFORM, "X returned no media id for the image")
            media_ids.append(media_id)
        return self._post(ctx, {"media_ids": media_ids}, transport)

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step:
        progress = dict(ctx.progress or {})
        if progress.get("post_id"):
            post_id = str(progress["post_id"])
            return Step(status=STEP_PUBLISHED, external_id=post_id, url=f"https://x.com/i/web/status/{post_id}",
                        progress=progress)
        media_id = str(progress.get("media_id") or "")
        if not media_id:
            raise PublishError(PLATFORM, "missing X media id to continue")
        resp = transport.request(
            "GET",
            f"{API}/media/upload",
            headers=_auth(ctx.access_token),
            params={"command": "STATUS", "media_id": media_id},
        )
        if not is_ok(resp):
            return Step(status=STEP_PROCESSING, external_id=media_id, progress=progress)
        info = (json_of(resp).get("data") or {}).get("processing_info") or {}
        state = str(info.get("state") or "").lower()
        if state == "failed":
            raise PublishError(PLATFORM, "X could not process the video")
        if state != "succeeded":
            return Step(status=STEP_PROCESSING, external_id=media_id, progress=progress,
                        note="X is processing the video.")
        return self._post(ctx, progress, transport)

    def _post(self, ctx: PublishContext, progress: dict, transport: Transport) -> Step:
        resp = transport.request(
            "POST",
            f"{API}/tweets",
            headers={**_auth(ctx.access_token), "Content-Type": "application/json"},
            json={"text": ctx.text,
                  "media": {"media_ids": list(progress.get("media_ids") or [progress["media_id"]])}},
        )
        if not is_ok(resp):
            raise fail(PLATFORM, "X refused the post", resp=resp)
        post_id = str((json_of(resp).get("data") or {}).get("id") or "")
        if not post_id:
            raise PublishError(PLATFORM, "X accepted the post but returned no id")
        return Step(status=STEP_PUBLISHED, external_id=post_id, url=f"https://x.com/i/web/status/{post_id}",
                    progress={**progress, "post_id": post_id})


register(XConnector())
