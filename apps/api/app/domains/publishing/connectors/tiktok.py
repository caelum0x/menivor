"""TikTok Content Posting API connector — Direct Post via PULL_FROM_URL.

Real flow (https://developers.tiktok.com/doc/content-posting-api-reference-direct-post):

1. **Init** — ``POST https://open.tiktokapis.com/v2/post/publish/video/init/``
   with ``Authorization: Bearer <token>`` and a JSON body carrying ``post_info``
   (title/caption, privacy level, interaction toggles) and ``source_info``
   (``source=PULL_FROM_URL`` + ``video_url`` — a public presigned R2 URL of the
   rendered MP4). Returns a ``publish_id``.
2. **Status** — ``POST /v2/post/publish/status/fetch/`` polls the ``publish_id``
   until ``PUBLISH_COMPLETE``. The connector performs one status fetch and
   returns ``processing`` when TikTok is still ingesting; the publish-status
   sweep then calls :meth:`TikTokConnector.resume` until it resolves.

PULL_FROM_URL requires the domain to be verified in the TikTok developer console;
the FILE_UPLOAD path (multipart) is the fallback and shares the same init body.

Error classification (``_classify_error``) ports the error-code → user-facing
message table from gitroomhq/postiz-app's ``tiktok.provider.ts`` (AGPL-3.0; see
``NOTICE`` at the repo root), the one concrete gap found when comparing this
connector against Postiz's: TikTok's ``init`` endpoint returns a stable
``error.code`` string (e.g. ``spam_risk_too_many_posts``,
``reached_active_user_cap``) that is far more actionable surfaced as a specific,
human message than the raw JSON body. Adapted to this module's conventions
(no literal code copied) and reduced to the codes relevant to PULL_FROM_URL
direct-post video flow.
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

_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
_MAX_TITLE = 2200  # TikTok caption limit

# Stable ``error.code`` substrings TikTok's Content Posting API returns, mapped
# to a specific, human message. ``retryable`` is True only for transient /
# rate-limit style codes a retry can plausibly resolve; everything else needs
# the creator to act (reconnect, wait a day, change TikTok privacy settings).
_ERROR_MESSAGES: tuple[tuple[str, str, bool], ...] = (
    ("reached_active_user_cap", "TikTok's daily app-wide posting limit was reached; reconnect the account tomorrow or ask the operator to raise the app's user cap", False),
    ("unaudited_client_can_only_post_to_private_accounts", "this TikTok developer app is not yet approved for public posts; post privately or complete TikTok's app audit", False),
    ("spam_risk_user_banned_from_posting", "TikTok has banned this account from posting", False),
    ("spam_risk_too_many_posts", "TikTok's daily post limit for this account was reached; try again tomorrow", True),
    ("spam_risk_too_many_pending_share", "TikTok limits pending posts to 5 per 24 hours; check the TikTok inbox and try again later", True),
    ("spam_risk", "TikTok flagged this post as potential spam", False),
    ("privacy_level_option_mismatch", "the requested privacy level isn't allowed for this TikTok account; check TikTok's privacy settings for this app", False),
    ("url_ownership_unverified", "TikTok rejected the video URL (domain not verified for PULL_FROM_URL)", False),
    ("video_pull_failed", "TikTok could not fetch the video from its URL", True),
    ("photo_pull_failed", "TikTok could not fetch the photo from its URL", True),
    ("frame_rate_check_failed", "the video's frame rate does not meet TikTok's specifications", False),
    ("invalid_file_upload", "the video file format doesn't meet TikTok's specifications", False),
)


def _classify_error(body: dict) -> tuple[str, bool] | None:
    """Map a known TikTok ``error.code``/message substring to (message, retryable).

    Returns ``None`` when nothing in :data:`_ERROR_MESSAGES` matches, so the
    caller falls back to the raw body (never hides an unrecognized error).
    """
    err = body.get("error") if isinstance(body, dict) else None
    haystack = " ".join(
        str(part) for part in (
            (err or {}).get("code") if isinstance(err, dict) else "",
            (err or {}).get("message") if isinstance(err, dict) else "",
            body,
        )
    ).lower()
    for needle, message, retryable in _ERROR_MESSAGES:
        if needle in haystack:
            return message, retryable
    return None


class TikTokConnector(PublishConnector):
    platform = "tiktok"

    def publish(self, req: PublishRequest, *, transport: Transport) -> PublishResult:
        if not req.access_token:
            raise PublishError(self.platform, "missing OAuth access token")
        if not req.video_url:
            raise PublishError(self.platform, "TikTok PULL_FROM_URL requires a public video_url")

        init = transport.request(
            "POST",
            _INIT_URL,
            headers=self._headers(req.access_token),
            json=self._init_body(req),
        )
        if not _ok(init):
            raw_body = _safe_json(init)
            classified = _classify_error(raw_body)
            raise PublishError(
                self.platform,
                classified[0] if classified else f"publish init failed (HTTP {init.status_code}): {raw_body}",
                retryable=classified[1] if classified else int(getattr(init, "status_code", 0)) >= 500,
            )
        body = _safe_json(init)
        # TikTok wraps errors in an `error` object even on HTTP 200.
        err = (body.get("error") or {})
        if str(err.get("code", "ok")).lower() not in ("ok", "", "none"):
            classified = _classify_error(body)
            raise PublishError(
                self.platform,
                classified[0] if classified else f"publish init rejected: {err}",
                retryable=classified[1] if classified else False,
            )
        publish_id = str((body.get("data") or {}).get("publish_id") or "")
        if not publish_id:
            raise PublishError(self.platform, f"init returned no publish_id: {body}")

        status = self._fetch_status(req.access_token, publish_id, transport)
        return PublishResult(
            platform=self.platform,
            status="published" if status == "PUBLISH_COMPLETE" else "processing",
            external_id=publish_id,
            url="",  # TikTok returns the post id asynchronously via the status fetch
            raw={"publish_id": publish_id, "status": status},
        )

    def resume(
        self, req: PublishRequest, external_id: str, *, transport: Transport
    ) -> PublishResult:
        """Re-poll a ``processing`` ``publish_id`` until TikTok finishes it.

        ``PUBLISH_COMPLETE`` resolves to ``published`` (with the public post URL
        when TikTok returns the post id); ``FAILED`` is terminal; anything else
        stays ``processing``.
        """
        if not req.access_token:
            raise PublishError(self.platform, "missing OAuth access token")
        data = self._fetch_status_data(req.access_token, external_id, transport)
        status = str(data.get("status") or "PROCESSING_UPLOAD")
        if status == "FAILED":
            reason = str(data.get("fail_reason") or "unknown reason")
            raise PublishError(self.platform, f"TikTok rejected the post: {reason}")
        if status != "PUBLISH_COMPLETE":
            return PublishResult(
                platform=self.platform,
                status="processing",
                external_id=external_id,
                raw={"publish_id": external_id, "status": status},
            )
        post_ids = data.get("publicaly_available_post_id") or data.get(
            "publicly_available_post_id"
        ) or []
        post_id = str(post_ids[0]) if isinstance(post_ids, list) and post_ids else ""
        url = f"https://www.tiktok.com/video/{post_id}" if post_id else ""
        return PublishResult(
            platform=self.platform,
            status="published",
            external_id=post_id or external_id,
            url=url,
            raw={"publish_id": external_id, "post_id": post_id, "status": status},
        )

    def _fetch_status_data(self, token: str, publish_id: str, transport: Transport) -> dict:
        resp = transport.request(
            "POST", _STATUS_URL, headers=self._headers(token), json={"publish_id": publish_id}
        )
        if not _ok(resp):
            return {"status": "PROCESSING_UPLOAD"}
        data = _safe_json(resp).get("data") or {}
        return data if isinstance(data, dict) else {"status": "PROCESSING_UPLOAD"}

    def _init_body(self, req: PublishRequest) -> dict:
        return {
            "post_info": {
                "title": req.caption_with_tags()[:_MAX_TITLE],
                "privacy_level": _privacy(req.privacy),
                "disable_duet": bool(req.extra.get("disable_duet", False)),
                "disable_comment": bool(req.extra.get("disable_comment", False)),
                "disable_stitch": bool(req.extra.get("disable_stitch", False)),
                # MN5: Menivor reels are AI-generated; TikTok's own AIGC label.
                "is_aigc": bool(req.extra.get("ai_generated", True)),
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": req.video_url,
            },
        }

    def _fetch_status(self, token: str, publish_id: str, transport: Transport) -> str:
        resp = transport.request(
            "POST", _STATUS_URL, headers=self._headers(token), json={"publish_id": publish_id}
        )
        if not _ok(resp):
            # A transient status error doesn't fail the publish — it's queued.
            return "PROCESSING_UPLOAD"
        return str((_safe_json(resp).get("data") or {}).get("status") or "PROCESSING_UPLOAD")

    @staticmethod
    def _headers(token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }


def _privacy(value: str) -> str:
    """Map to TikTok's privacy enum (default: only the creator can see it)."""
    mapping = {
        "public": "PUBLIC_TO_EVERYONE",
        "friends": "MUTUAL_FOLLOW_FRIENDS",
        "private": "SELF_ONLY",
        "unlisted": "SELF_ONLY",
    }
    return mapping.get(str(value or "").strip().lower(), "SELF_ONLY")


register_connector(TikTokConnector())
