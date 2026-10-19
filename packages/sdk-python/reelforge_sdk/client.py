"""ReelForge Python SDK.

A tiny, standard-library-only client for the public ReelForge ``/api/v1``
surface (jobs, presigned uploads, webhook subscriptions, developer portal,
workspace usage, and the current-user profile).

Every ReelForge response uses the envelope ``{"status": ..., "data": ...}``;
:class:`ReelForgeClient` unwraps and returns the ``data`` payload directly and
raises :class:`ReelForgeApiError` for any non-2xx status.

The transport uses ``httpx`` when it is installed (connection pooling, timeouts)
and transparently falls back to :mod:`urllib` from the standard library, so the
package has **no required dependencies**.

Example
-------
>>> from reelforge_sdk import ReelForgeClient
>>> rf = ReelForgeClient(api_key="rf_...")          # doctest: +SKIP
>>> me = rf.me()                                     # doctest: +SKIP
>>> job = rf.create_job({"params": {"script": "hi"}})  # doctest: +SKIP
>>> status = rf.get_job(job["job_id"])               # doctest: +SKIP
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

from .errors import ReelForgeApiError
from .resources import (
    BrollResource,
    ClipmarketResource,
    JobsResource,
    MediaResource,
    RenderResource,
    TemplatesResource,
    UploadsResource,
    WebhooksResource,
    WorkspacesResource,
)

__all__ = [
    "ReelForgeClient",
    "ReelForgeApiError",
    "WEBHOOK_EVENT_TYPES",
    "__version__",
]

__version__ = "0.1.0"

#: Supported webhook event types (mirrors the server catalog).
WEBHOOK_EVENT_TYPES: tuple[str, ...] = (
    "job.completed",
    "publish.succeeded",
    "publish.failed",
    "performance.ingested",
)

_DEFAULT_BASE_URL = "https://api.menivor.com"
_DEFAULT_TIMEOUT = 30.0


class ReelForgeClient:
    """A thin, typed client for the ReelForge ``/api/v1`` platform.

    Parameters
    ----------
    api_key:
        Per-user API key, sent as the ``x-api-key`` header on every request.
    base_url:
        API origin (defaults to ``https://api.menivor.com``). A trailing slash
        is stripped.
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise ValueError("ReelForgeClient: `api_key` is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._httpx_client = self._maybe_build_httpx_client()
        self.jobs = JobsResource(self)
        self.broll = BrollResource(self)
        self.uploads = UploadsResource(self)
        self.webhooks = WebhooksResource(self)
        self.workspaces = WorkspacesResource(self)
        self.templates = TemplatesResource(self)
        self.render = RenderResource(self)
        self.clipmarket = ClipmarketResource(self)
        self.media = MediaResource(self)

    # ------------------------------------------------------------------ #
    # Current user
    # ------------------------------------------------------------------ #
    def me(self) -> Dict[str, Any]:
        """``GET /me`` — the authenticated caller's profile + credit balance."""
        return self._request("GET", "/me")

    # ------------------------------------------------------------------ #
    # Jobs
    # ------------------------------------------------------------------ #
    def create_job(
        self, body: Dict[str, Any], *, idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """``POST /jobs`` — create (and enqueue) one or more avatar jobs."""
        return self.jobs.create(body, idempotency_key=idempotency_key)

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """``GET /jobs/{id}`` — fetch a single job's status."""
        return self.jobs.get(job_id)

    def list_jobs(
        self, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> Dict[str, Any]:
        """``GET /jobs`` — list the caller's jobs (newest first)."""
        return self.jobs.list(limit=limit, offset=offset)

    def retry_job(self, job_id: str) -> Dict[str, Any]:
        """``POST /jobs/{id}/retry`` — re-enqueue a failed job."""
        return self.jobs.retry(job_id)

    def rerun_job(
        self, job_id: str, body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """``POST /jobs/{id}/rerun`` — clone a job's params with tweaks."""
        return self.jobs.rerun(job_id, body)

    def get_batch(self, batch_id: str) -> Dict[str, Any]:
        """``GET /batches/{id}`` — review every variant job of a batch."""
        return self.jobs.get_batch(batch_id)

    def export_editor_cut(
        self,
        job_id: str,
        *,
        in_point: float,
        out_point: float,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Queue an exact non-destructive cut of a completed reel."""
        return self.jobs.export_cut(
            job_id,
            in_point=in_point,
            out_point=out_point,
            idempotency_key=idempotency_key,
        )

    def generate_broll(
        self, body: Dict[str, Any], *, idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Start a canonical AI B-roll generation."""
        return self.broll.generate(body, idempotency_key=idempotency_key)

    def get_broll_generation(self, generation_id: str) -> Dict[str, Any]:
        """Fetch one owner-scoped AI B-roll generation."""
        return self.broll.get(generation_id)

    def list_broll_generations(self) -> List[Dict[str, Any]]:
        """List the caller's durable AI B-roll generation history."""
        return self.broll.list()

    # ------------------------------------------------------------------ #
    # Uploads
    # ------------------------------------------------------------------ #
    def presign_upload(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """``POST /uploads/presign`` — presigned PUT + GET URLs for an upload."""
        return self.uploads.presign(body)

    def register_upload(self, key: str, kind: str = "upload") -> Dict[str, Any]:
        """Register a completed direct upload as caller-owned media."""
        return self.uploads.register(key, kind)

    # ------------------------------------------------------------------ #
    # Webhook subscriptions (workspace/tenant-scoped)
    # ------------------------------------------------------------------ #
    def create_webhook_subscription(
        self, workspace_id: str, url: str, event_types: Sequence[str]
    ) -> Dict[str, Any]:
        """``POST /me/workspaces/{ws}/webhooks`` — create a subscription.

        The signing ``secret`` is returned exactly once, in this response. Store
        it now — list/get/delivery views never return it again.
        """
        return self.webhooks.create(workspace_id, url, event_types)

    def list_webhook_subscriptions(self, workspace_id: str) -> List[Dict[str, Any]]:
        """``GET /me/workspaces/{ws}/webhooks`` — list subscriptions (secret-free)."""
        return self.webhooks.list(workspace_id)

    def delete_webhook_subscription(
        self, workspace_id: str, subscription_id: str
    ) -> Dict[str, Any]:
        """``DELETE /me/workspaces/{ws}/webhooks/{id}`` — revoke a subscription."""
        return self.webhooks.delete(workspace_id, subscription_id)

    def test_webhook_subscription(
        self, workspace_id: str, subscription_id: str
    ) -> Dict[str, Any]:
        """``POST /me/workspaces/{ws}/webhooks/{id}/test`` — send a signed test event."""
        return self.webhooks.test(workspace_id, subscription_id)

    def list_webhook_deliveries(
        self,
        workspace_id: str,
        subscription_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """``GET /me/workspaces/{ws}/webhooks/{id}/deliveries`` — recent deliveries."""
        return self.webhooks.deliveries(workspace_id, subscription_id, limit)

    # ------------------------------------------------------------------ #
    # Developer portal
    # ------------------------------------------------------------------ #
    def get_developer_portal(self) -> Dict[str, Any]:
        """``GET /me/developer`` — the caller-scoped developer portal summary."""
        return self._request("GET", "/me/developer")

    # ------------------------------------------------------------------ #
    # Usage + entitlements (workspace/tenant-scoped)
    # ------------------------------------------------------------------ #
    def get_usage(
        self, workspace_id: str, period: Optional[str] = None
    ) -> Dict[str, Any]:
        """``GET /me/workspaces/{ws}/usage`` — metered usage + overage."""
        return self.workspaces.usage(workspace_id, period)

    def get_entitlements(self, workspace_id: str) -> Dict[str, Any]:
        """``GET /me/workspaces/{ws}/entitlements`` — active-plan entitlements."""
        return self.workspaces.entitlements(workspace_id)

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        """Close the underlying ``httpx`` client, if one is in use."""
        if self._httpx_client is not None:
            self._httpx_client.close()

    def __enter__(self) -> "ReelForgeClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def _maybe_build_httpx_client(self) -> Any:
        """Build an ``httpx.Client`` when available, else ``None`` (urllib path)."""
        try:
            import httpx  # type: ignore
        except Exception:  # noqa: BLE001 - httpx is optional
            return None
        return httpx.Client(timeout=self.timeout)

    def _url(self, path: str, query: Optional[Dict[str, Any]]) -> str:
        url = f"{self.base_url}/api/v1{path}"
        if query:
            filtered = {k: v for k, v in query.items() if v is not None}
            if filtered:
                url += "?" + urllib.parse.urlencode(filtered)
        return url

    def _headers(self, has_body: bool) -> Dict[str, str]:
        headers = {"x-api-key": self.api_key, "accept": "application/json"}
        if has_body:
            headers["content-type"] = "application/json"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        url = self._url(path, query)
        request_headers = self._headers(body is not None)
        if headers:
            request_headers.update(headers)
        raw = json.dumps(body).encode("utf-8") if body is not None else None

        if self._httpx_client is not None:
            status, text, correlation_id = self._send_httpx(
                method, url, request_headers, raw
            )
        else:
            status, text, correlation_id = self._send_urllib(
                method, url, request_headers, raw
            )

        return self._handle(status, text, correlation_id)

    def _send_httpx(
        self, method: str, url: str, headers: Dict[str, str], raw: Optional[bytes]
    ) -> tuple[int, str, str]:
        response = self._httpx_client.request(method, url, headers=headers, content=raw)
        return (
            response.status_code,
            response.text,
            str(response.headers.get("X-Correlation-ID") or ""),
        )

    def _send_urllib(
        self, method: str, url: str, headers: Dict[str, str], raw: Optional[bytes]
    ) -> tuple[int, str, str]:
        req = urllib.request.Request(url, data=raw, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return (
                    resp.getcode(),
                    resp.read().decode("utf-8"),
                    str(resp.headers.get("X-Correlation-ID") or ""),
                )
        except urllib.error.HTTPError as exc:
            # A non-2xx status is delivered as an exception by urllib; recover
            # the status + body so it flows through the normal error handler.
            body = exc.read().decode("utf-8") if exc.fp is not None else ""
            response_headers = getattr(exc, "headers", None)
            return (
                exc.code,
                body,
                str(
                    (response_headers.get("X-Correlation-ID") or "")
                    if response_headers is not None
                    else ""
                ),
            )

    def _handle(self, status: int, text: str, correlation_id: str = "") -> Any:
        parsed: Any = None
        if text:
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None

        if status < 200 or status >= 300:
            message = ""
            if isinstance(parsed, dict):
                message = str(parsed.get("message") or "")
            raise ReelForgeApiError(
                status,
                message or f"HTTP {status}",
                parsed if parsed is not None else text,
                correlation_id,
            )

        # Unwrap the ``{"status": ..., "data": ...}`` envelope. ``data`` is
        # omitted by the server when falsy, so fall back to the envelope itself.
        if isinstance(parsed, dict) and "data" in parsed:
            return parsed["data"]
        return parsed


def _quote(value: str) -> str:
    """URL-encode a single path segment (no slashes leak through)."""
    return urllib.parse.quote(str(value), safe="")
