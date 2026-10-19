"""Instagram Graph API connector — Reels via container + publish.

Real two-step flow (https://developers.facebook.com/docs/instagram-api/guides/content-publishing):

1. **Create container** — ``POST https://graph.facebook.com/v21.0/{ig-user-id}/media``
   with ``media_type=REELS``, ``video_url`` (a public presigned R2 URL of the MP4),
   ``caption`` and ``access_token``. Returns a container ``id`` (creation id).
2. **Publish** — ``POST /{ig-user-id}/media_publish`` with ``creation_id`` +
   ``access_token``. Returns the published media ``id``.

Instagram ingests the video from ``video_url`` asynchronously; the container is
not immediately publishable. The connector performs one status check
(``GET /{creation_id}?fields=status_code``) and publishes when ``FINISHED``,
otherwise returns ``processing``; the publish-status sweep
(``sweep_processing_publishes_task``) later calls :meth:`resume`, which re-checks
the container and runs ``media_publish`` once it is ``FINISHED``.
"""

from __future__ import annotations

from .base import (
    PublishConnector,
    PublishError,
    PublishRequest,
    PublishResult,
    Transport,
    _ok,
    _safe_json,
    register_connector,
)

_GRAPH = "https://graph.facebook.com/v21.0"


class InstagramConnector(PublishConnector):
    platform = "instagram"

    def publish(self, req: PublishRequest, *, transport: Transport) -> PublishResult:
        if not req.access_token:
            raise PublishError(self.platform, "missing OAuth access token")
        if not req.external_account_id:
            raise PublishError(self.platform, "missing Instagram user id (external_account_id)")
        if not req.video_url:
            raise PublishError(self.platform, "Instagram Reels requires a public video_url")

        creation_id = self._create_container(req, transport)
        status = self._container_status(req, creation_id, transport)
        if status != "FINISHED":
            # Not ready to publish yet — hand back the creation id to re-publish.
            return PublishResult(
                platform=self.platform,
                status="processing",
                external_id=creation_id,
                raw={"creation_id": creation_id, "status": status},
            )
        return self._publish_container(req, creation_id, transport)

    def resume(
        self, req: PublishRequest, external_id: str, *, transport: Transport
    ) -> PublishResult:
        """Re-poll a ``processing`` container and publish it once ``FINISHED``.

        ``external_id`` is the container (creation) id returned by
        :meth:`publish`. ``ERROR``/``EXPIRED`` containers fail terminally (the
        creator must publish again); anything else stays ``processing``.
        """
        if not req.access_token or not req.external_account_id:
            raise PublishError(self.platform, "missing OAuth access token or Instagram user id")
        status = self._container_status(req, external_id, transport)
        if status == "FINISHED":
            return self._publish_container(req, external_id, transport)
        if status in ("ERROR", "EXPIRED"):
            raise PublishError(
                self.platform, f"Instagram could not process the reel (status={status})"
            )
        if status == "PUBLISHED":
            # Already published by an earlier resume whose result was not saved.
            return PublishResult(
                platform=self.platform,
                status="published",
                external_id=external_id,
                raw={"creation_id": external_id, "status": status},
            )
        return PublishResult(
            platform=self.platform,
            status="processing",
            external_id=external_id,
            raw={"creation_id": external_id, "status": status},
        )

    def _create_container(self, req: PublishRequest, transport: Transport) -> str:
        resp = transport.request(
            "POST",
            f"{_GRAPH}/{req.external_account_id}/media",
            params={
                "media_type": "REELS",
                "video_url": req.video_url,
                "caption": req.caption_with_tags(),
                "share_to_feed": "true",
                "access_token": req.access_token,
            },
        )
        if not _ok(resp):
            raise PublishError(
                self.platform,
                f"container create failed (HTTP {resp.status_code}): {_safe_json(resp)}",
                retryable=int(getattr(resp, "status_code", 0)) >= 500,
            )
        cid = str(_safe_json(resp).get("id") or "")
        if not cid:
            raise PublishError(self.platform, f"container create returned no id: {_safe_json(resp)}")
        return cid

    def _container_status(self, req: PublishRequest, creation_id: str, transport: Transport) -> str:
        resp = transport.request(
            "GET",
            f"{_GRAPH}/{creation_id}",
            params={"fields": "status_code", "access_token": req.access_token},
        )
        if not _ok(resp):
            return "IN_PROGRESS"
        return str(_safe_json(resp).get("status_code") or "IN_PROGRESS")

    def _publish_container(self, req: PublishRequest, creation_id: str, transport: Transport) -> PublishResult:
        resp = transport.request(
            "POST",
            f"{_GRAPH}/{req.external_account_id}/media_publish",
            params={"creation_id": creation_id, "access_token": req.access_token},
        )
        if not _ok(resp):
            raise PublishError(
                self.platform,
                f"media_publish failed (HTTP {resp.status_code}): {_safe_json(resp)}",
                retryable=int(getattr(resp, "status_code", 0)) >= 500,
            )
        media_id = str(_safe_json(resp).get("id") or "")
        if not media_id:
            raise PublishError(self.platform, f"media_publish returned no id: {_safe_json(resp)}")
        return PublishResult(
            platform=self.platform,
            status="published",
            external_id=media_id,
            url=f"https://www.instagram.com/reel/{media_id}/",
            raw={"creation_id": creation_id, "media_id": media_id},
        )


register_connector(InstagramConnector())
