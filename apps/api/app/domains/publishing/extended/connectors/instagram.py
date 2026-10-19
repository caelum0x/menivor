"""Instagram image posts (Design Studio pages) through the Instagram Graph API.

Reels keep using the native connector (:mod:`app.domains.publishing.connectors.instagram`);
this module only publishes images, reusing the same Graph API host and the
creator's native Instagram connection:

1. one page: ``POST /{ig-user-id}/media`` with ``image_url`` + ``caption``;
   several pages (2-10): one ``is_carousel_item`` container per page, then a
   ``media_type=CAROUSEL`` container with ``children``;
2. ``GET /{container-id}?fields=status_code`` until ``FINISHED`` (reported as a
   ``processing`` step so the due-runner polls instead of blocking);
3. ``POST /{ig-user-id}/media_publish`` with ``creation_id``;
4. ``GET /{media-id}?fields=permalink`` for the public URL.

Instagram only accepts JPEG images, so the scheduler stores JPEG copies of the
design pages for Instagram posts.
"""

from __future__ import annotations

from app.domains.publishing.connectors.instagram import _GRAPH as GRAPH

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
    register_image_only,
)

PLATFORM = "instagram"
MAX_CAROUSEL = 10


class InstagramImageConnector:
    platform = PLATFORM

    def _require(self, ctx: PublishContext) -> None:
        if not ctx.access_token or not ctx.external_account_id:
            raise PublishError(PLATFORM, "missing Instagram token or account id; reconnect Instagram")

    def _container(self, ctx: PublishContext, params: dict, transport: Transport, what: str) -> str:
        resp = transport.request("POST", f"{GRAPH}/{ctx.external_account_id}/media",
                                 params={**params, "access_token": ctx.access_token})
        if not is_ok(resp):
            raise fail(PLATFORM, f"Instagram refused the {what}", resp=resp)
        container = str(json_of(resp).get("id") or "")
        if not container:
            raise PublishError(PLATFORM, "Instagram returned no media container id")
        return container

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step:
        self._require(ctx)
        if not ctx.is_image_post:
            raise PublishError(PLATFORM, "reels publish through the native Instagram connector")
        urls = list(ctx.image_urls)
        if not urls:
            raise PublishError(PLATFORM, "Instagram needs public image URLs to fetch the design")
        if len(urls) > MAX_CAROUSEL:
            raise PublishError(PLATFORM, f"Instagram carousels take at most {MAX_CAROUSEL} images")
        if len(urls) == 1:
            container = self._container(ctx, {"image_url": urls[0], "caption": ctx.text}, transport, "image")
        else:
            children = [
                self._container(ctx, {"image_url": url, "is_carousel_item": "true"}, transport, "carousel image")
                for url in urls
            ]
            container = self._container(
                ctx, {"media_type": "CAROUSEL", "children": ",".join(children), "caption": ctx.text},
                transport, "carousel",
            )
        return self._advance(ctx, {"container_id": container}, transport)

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step:
        self._require(ctx)
        progress = dict(ctx.progress or {})
        if progress.get("media_id"):
            return Step(status=STEP_PUBLISHED, external_id=str(progress["media_id"]),
                        url=str(progress.get("permalink") or ""), progress=progress)
        if not progress.get("container_id"):
            raise PublishError(PLATFORM, "missing Instagram container to continue")
        return self._advance(ctx, progress, transport)

    def _advance(self, ctx: PublishContext, progress: dict, transport: Transport) -> Step:
        container = str(progress["container_id"])
        resp = transport.request("GET", f"{GRAPH}/{container}",
                                 params={"fields": "status_code", "access_token": ctx.access_token})
        status = str(json_of(resp).get("status_code") or "").upper() if is_ok(resp) else ""
        if status in ("ERROR", "EXPIRED"):
            raise PublishError(PLATFORM, f"Instagram could not process the images (status={status})")
        if status != "FINISHED":
            return Step(status=STEP_PROCESSING, external_id=container, progress=progress,
                        note="Instagram is processing the images.")
        pub = transport.request("POST", f"{GRAPH}/{ctx.external_account_id}/media_publish",
                                params={"creation_id": container, "access_token": ctx.access_token})
        if not is_ok(pub):
            raise fail(PLATFORM, "Instagram refused to publish the post", resp=pub)
        media_id = str(json_of(pub).get("id") or "")
        if not media_id:
            raise PublishError(PLATFORM, "Instagram published but returned no media id")
        url = ""
        link = transport.request("GET", f"{GRAPH}/{media_id}",
                                 params={"fields": "permalink", "access_token": ctx.access_token})
        if is_ok(link):
            url = str(json_of(link).get("permalink") or "")
        return Step(status=STEP_PUBLISHED, external_id=media_id, url=url,
                    progress={**progress, "media_id": media_id, "permalink": url})


register_image_only(InstagramImageConnector())
