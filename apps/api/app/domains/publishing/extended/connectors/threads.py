"""Threads video post (Threads API, two-step container publish).

1. ``POST /v1.0/{user-id}/threads`` with ``media_type=VIDEO``, ``video_url``
   and ``text`` -> a media container id.
2. ``GET /v1.0/{container-id}?fields=status,error_message`` until ``FINISHED``.
3. ``POST /v1.0/{user-id}/threads_publish`` with ``creation_id`` -> the post id.
4. ``GET /v1.0/{post-id}?fields=permalink`` for the public URL.

Image posts use the same container flow: one image is ``media_type=IMAGE``
with ``image_url``; several become ``is_carousel_item`` children of a
``media_type=CAROUSEL`` container (2-20 items).
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
    is_ok,
    json_of,
    register,
)

PLATFORM = "threads"
API = "https://graph.threads.net/v1.0"
MAX_CAROUSEL = 20


class ThreadsConnector:
    platform = PLATFORM

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step:
        if not ctx.access_token or not ctx.external_account_id:
            raise PublishError(PLATFORM, "missing Threads token or user id; reconnect Threads")
        if ctx.is_image_post:
            return self._advance(ctx, {"container_id": self._image_container(ctx, transport), "kind": "image"},
                                 transport)
        if not ctx.video_url:
            raise PublishError(PLATFORM, "Threads needs a public video URL to fetch the reel")
        resp = transport.request(
            "POST",
            f"{API}/{ctx.external_account_id}/threads",
            params={
                "media_type": "VIDEO",
                "video_url": ctx.video_url,
                "text": ctx.text,
                "access_token": ctx.access_token,
            },
        )
        if not is_ok(resp):
            raise fail(PLATFORM, "Threads refused the video", resp=resp)
        container = str(json_of(resp).get("id") or "")
        if not container:
            raise PublishError(PLATFORM, "Threads returned no media container id")
        return self._advance(ctx, {"container_id": container}, transport)

    def _create(self, ctx: PublishContext, params: dict, transport: Transport, what: str) -> str:
        resp = transport.request("POST", f"{API}/{ctx.external_account_id}/threads",
                                 params={**params, "access_token": ctx.access_token})
        if not is_ok(resp):
            raise fail(PLATFORM, f"Threads refused the {what}", resp=resp)
        container = str(json_of(resp).get("id") or "")
        if not container:
            raise PublishError(PLATFORM, "Threads returned no media container id")
        return container

    def _image_container(self, ctx: PublishContext, transport: Transport) -> str:
        urls = list(ctx.image_urls)
        if not urls:
            raise PublishError(PLATFORM, "Threads needs public image URLs to fetch the design")
        if len(urls) > MAX_CAROUSEL:
            raise PublishError(PLATFORM, f"Threads carousels take at most {MAX_CAROUSEL} images")
        if len(urls) == 1:
            return self._create(ctx, {"media_type": "IMAGE", "image_url": urls[0], "text": ctx.text},
                                transport, "image")
        children = [
            self._create(ctx, {"media_type": "IMAGE", "image_url": url, "is_carousel_item": "true"},
                         transport, "carousel image")
            for url in urls
        ]
        return self._create(ctx, {"media_type": "CAROUSEL", "children": ",".join(children), "text": ctx.text},
                            transport, "carousel")

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step:
        progress = dict(ctx.progress or {})
        if progress.get("post_id"):
            return Step(status=STEP_PUBLISHED, external_id=str(progress["post_id"]), progress=progress)
        if not progress.get("container_id"):
            raise PublishError(PLATFORM, "missing Threads container to continue")
        return self._advance(ctx, progress, transport)

    def _advance(self, ctx: PublishContext, progress: dict, transport: Transport) -> Step:
        container = progress["container_id"]
        resp = transport.request(
            "GET", f"{API}/{container}",
            params={"fields": "status,error_message", "access_token": ctx.access_token},
        )
        if not is_ok(resp):
            return Step(status=STEP_PROCESSING, external_id=container, progress=progress)
        body = json_of(resp)
        status = str(body.get("status") or "").upper()
        if status in ("ERROR", "EXPIRED"):
            reason = str(body.get("error_message") or status.lower())
            what = "images" if progress.get("kind") == "image" else "video"
            raise PublishError(PLATFORM, f"Threads could not process the {what} ({reason})")
        if status == "IN_PROGRESS" or status == "":
            what = "images" if progress.get("kind") == "image" else "video"
            return Step(status=STEP_PROCESSING, external_id=container, progress=progress,
                        note=f"Threads is processing the {what}.")

        pub = transport.request(
            "POST",
            f"{API}/{ctx.external_account_id}/threads_publish",
            params={"creation_id": container, "access_token": ctx.access_token},
        )
        if not is_ok(pub):
            raise fail(PLATFORM, "Threads refused to publish the post", resp=pub)
        post_id = str(json_of(pub).get("id") or "")
        if not post_id:
            raise PublishError(PLATFORM, "Threads published but returned no post id")
        url = ""
        link = transport.request(
            "GET", f"{API}/{post_id}", params={"fields": "permalink", "access_token": ctx.access_token}
        )
        if is_ok(link):
            url = str(json_of(link).get("permalink") or "")
        return Step(status=STEP_PUBLISHED, external_id=post_id, url=url, progress={**progress, "post_id": post_id})


register(ThreadsConnector())
