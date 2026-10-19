"""Live :class:`~app.services.publishers.base.VideoUploadClient` implementation.

This is the real network client the publisher seam was designed to accept. It
does **not** reimplement each platform's HTTP flow — those documented flows
already live, fully implemented and tested, in
:mod:`app.domains.publishing.connectors` (TikTok Content Posting API, Instagram
Graph API Reels, YouTube Data API v3 resumable upload). This client is the thin
adapter that lets the ``services/publishers`` seam drive that single, canonical
implementation, so there is exactly one place that talks to each platform.

What it adds on top of the connectors:

* **Env-based credential fallback.** When the caller does not supply a decrypted
  per-user token, the bearer token is taken from ``<PLATFORM>_ACCESS_TOKEN`` (see
  :mod:`app.services.publishers.env_creds`). The Instagram user id likewise falls
  back to ``INSTAGRAM_EXTERNAL_ACCOUNT_ID``.
* **Clean degradation.** When no usable token exists (neither a supplied token
  nor an env token) the client raises a clear :class:`PublishError` — it never
  makes a half-formed request and never crashes the process.
* **Injectable transport.** The underlying HTTP boundary is the connectors'
  :class:`~app.domains.publishing.connectors.Transport`; pass a fake in tests to
  assert the exact request shapes without touching the network.
"""

from __future__ import annotations

import os
from typing import Any

from app.services.publishers.base import PublishError
from app.services.publishers.env_creds import (
    normalize_platform,
    resolve_platform_creds,
)

# YouTube uploads video *bytes*; when only a URL is available we stream it to a
# temp file below this size ceiling first (defensive — the render output is a
# short vertical clip). Kept as a constant, not a magic number.
_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024  # 512 MiB


class NativeUploadClient:
    """A live upload client that delegates to the native platform connectors.

    Construction takes an optional ``transport`` (the network seam); tests inject
    a fake, production leaves it ``None`` so each publish uses a fresh
    ``requests``-backed transport.
    """

    def __init__(self, transport: Any | None = None) -> None:
        self._transport = transport

    def upload(
        self,
        provider: str,
        access_token: str,
        video_url: str,
        *,
        caption: str = "",
        **options: Any,
    ) -> dict[str, Any]:
        """Upload ``video_url`` to ``provider`` and return the raw provider response.

        ``access_token`` is the decrypted per-user token when the caller has one;
        an empty value falls back to ``<PLATFORM>_ACCESS_TOKEN``. Raises
        :class:`PublishError` when the platform is unknown, no token can be
        resolved, or the connector rejects the publish.
        """
        # Imported lazily so importing the publisher seam never pulls the
        # connector registry (and its optional deps) at app startup.
        from app.domains.publishing.connectors import (
            PublishError as ConnectorPublishError,
            PublishRequest,
            RequestsTransport,
            get_connector,
        )

        platform = normalize_platform(provider)
        creds = resolve_platform_creds(platform)

        token = (access_token or "").strip() or creds.access_token
        if not token:
            raise PublishError(
                f"no access token for {platform!r}: supply a connected account "
                f"or set {platform.upper()}_ACCESS_TOKEN"
            )

        connector = get_connector(platform)
        if connector is None:
            raise PublishError(f"unsupported publish platform: {platform!r}")

        external_account_id = str(
            options.get("external_account_id") or creds.external_account_id or ""
        )
        hashtags = tuple(str(t) for t in (options.get("hashtags") or ()) if str(t))
        privacy = str(options.get("privacy", "public") or "public")

        video_path = str(options.get("video_path", "") or "")
        temp_path = ""
        try:
            # YouTube needs local bytes; download the presigned URL when the caller
            # only handed us a URL (TikTok/Instagram ingest the URL directly).
            if platform == "youtube" and not video_path and video_url:
                temp_path = _download_to_temp(video_url)
                video_path = temp_path

            req = PublishRequest(
                platform=platform,
                access_token=token,
                video_url=video_url,
                video_path=video_path,
                title=str(options.get("title", "") or ""),
                description=str(options.get("description", "") or ""),
                caption=caption,
                hashtags=hashtags,
                privacy=privacy,
                external_account_id=external_account_id,
                extra=dict(options.get("extra") or {}),
            )

            try:
                result = connector.publish(
                    req, transport=self._transport or RequestsTransport()
                )
            except ConnectorPublishError as exc:
                # Re-map the connector's error type to the seam's PublishError so
                # BasePublisher callers see the contract they expect.
                raise PublishError(str(exc)) from exc
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:  # pragma: no cover - best-effort cleanup
                    pass

        if result.status == "failed":
            raise PublishError(f"{platform} publish failed: {result.raw or {}}")

        raw = dict(result.raw) if isinstance(result.raw, dict) else {}
        # id/url are written last so they always reflect the parsed result and are
        # never shadowed by a same-named key inside the provider's raw payload.
        return {
            **raw,
            "status": result.status,
            "platform": result.platform,
            "id": result.external_id,
            "url": result.url,
        }


def _download_to_temp(url: str) -> str:
    """Stream a presigned video URL to a temp MP4 for byte-upload (YouTube)."""
    import tempfile

    import requests

    fd, path = tempfile.mkstemp(prefix="publish_", suffix=".mp4")
    written = 0
    try:
        with requests.get(url, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with os.fdopen(fd, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > _MAX_DOWNLOAD_BYTES:
                        raise PublishError("video exceeds the max upload size")
                    fh.write(chunk)
    except Exception:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:  # pragma: no cover - best-effort cleanup
                pass
        raise
    return path


__all__ = ["NativeUploadClient"]
