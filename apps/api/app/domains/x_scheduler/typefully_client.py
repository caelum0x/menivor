"""Typefully API v2 (https://api.typefully.com/v2, Bearer API key).

Social sets are the accounts. A draft is ``POST /v2/social-sets/{id}/drafts``
with ``publish_at`` of ``now``, ``next-free-slot``, or an ISO time. Media is
not a URL: create an upload, PUT the raw bytes to the presigned URL with no
extra headers, wait until the media is ``ready``, then attach ``media_ids``.
HTTP 402 means the account is paused or out of free-plan publishing quota.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app.domains.x_scheduler.errors import LimitReached, redact
from app.domains.x_scheduler.http import ProviderHTTPError, Transport, default_transport, put_bytes, request_json

API = "https://api.typefully.com/v2"
_PUBLISH_AT = {"now": "now", "queue": "next-free-slot"}


class TypefullyClient:
    def __init__(
        self,
        api_key: str,
        transport: Transport | None = None,
        *,
        sleep: Callable[[float], None] | None = None,
        poll_attempts: int = 8,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self._transport = transport or default_transport
        self._sleep = sleep or time.sleep
        self._poll_attempts = max(1, poll_attempts)

    def list_x_social_sets(self) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []
        offset = 0
        while offset < 200:
            page = self._json("GET", f"/social-sets?limit=50&offset={offset}")
            rows = page.get("results") if isinstance(page, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                if not isinstance(row, dict) or row.get("id") is None:
                    continue
                detail = self._json("GET", f"/social-sets/{row['id']}/")
                if not isinstance(detail, dict):
                    continue
                platforms = detail.get("platforms") if isinstance(detail.get("platforms"), dict) else {}
                x_account = platforms.get("x")
                if not x_account:
                    continue
                handle = ""
                if isinstance(x_account, dict):
                    handle = str(x_account.get("username") or x_account.get("name") or "")
                handle = handle or str(detail.get("username") or detail.get("name") or row["id"])
                team = detail.get("team") if isinstance(detail.get("team"), dict) else {}
                quota = _quota(detail.get("publishing_quota"))
                targets.append({
                    "id": str(row["id"]),
                    "name": str(detail.get("name") or handle),
                    "handle": handle,
                    "organization": str(team.get("name") or ""),
                    "service": "x",
                    "provider": "typefully",
                    "publishing_quota": quota,
                })
            next_page = page.get("next") if isinstance(page, dict) else None
            offset += len(rows)
            if not next_page or len(rows) < 50:
                break
        return targets

    def publish(
        self,
        *,
        social_set_id: str,
        text: str,
        filename: str,
        data: bytes,
        when: str,
        due_at: str | None,
        quota: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if quota is None:
            detail = self._json("GET", f"/social-sets/{social_set_id}/")
            quota = _quota(detail.get("publishing_quota")) if isinstance(detail, dict) else None
        if quota and quota.get("remaining") == 0:
            when_reset = quota.get("resets_at") or "the next monthly reset"
            raise LimitReached(
                "Typefully's monthly publishing quota for this account is used up "
                f"(free plans have a monthly limit). It resets {when_reset}. Nothing was posted."
            )
        created = self._json(
            "POST",
            f"/social-sets/{social_set_id}/media/upload",
            {"file_name": filename},
            ok=(200, 201),
        )
        media_id = str((created or {}).get("media_id") or "")
        upload_url = str((created or {}).get("upload_url") or "")
        if not media_id or not upload_url.startswith("https://"):
            raise ProviderHTTPError(502, "Typefully did not return a media upload URL.")
        put_bytes(self._transport, upload_url, data, secret=self.api_key)
        self._wait_until_ready(social_set_id, media_id)
        publish_at = _PUBLISH_AT.get(when) or due_at
        draft = self._json(
            "POST",
            f"/social-sets/{social_set_id}/drafts",
            {
                "platforms": {"x": {"enabled": True, "posts": [{"text": text, "media_ids": [media_id]}]}},
                "publish_at": publish_at,
            },
            ok=(200, 201),
        )
        return {
            "id": str((draft or {}).get("id") or (draft or {}).get("draft_id") or ""),
            "status": _draft_status(when, draft if isinstance(draft, dict) else {}),
            "private_url": str((draft or {}).get("private_url") or ""),
        }

    def _wait_until_ready(self, social_set_id: str, media_id: str) -> None:
        last = "processing"
        for attempt in range(self._poll_attempts):
            status = self._json("GET", f"/social-sets/{social_set_id}/media/{media_id}")
            last = str((status or {}).get("status") or "")
            if last == "ready":
                return
            if last == "failed":
                raise ProviderHTTPError(422, "Typefully could not process that media file. Nothing was posted.")
            if attempt + 1 < self._poll_attempts:
                self._sleep(0.4)
        raise ProviderHTTPError(422, f"Typefully is still processing the media ({last or 'unknown'}). Nothing was posted.")

    def _json(self, method: str, path: str, body: dict | None = None, *, ok: tuple[int, ...] = (200,)) -> Any:
        if not self.api_key:
            raise ProviderHTTPError(401, "Typefully API key is missing.")
        try:
            return request_json(
                self._transport,
                method,
                f"{API}{path}",
                {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                body,
                secret=self.api_key,
                ok=ok,
            )
        except ProviderHTTPError as exc:
            if exc.status in (401, 403) and method == "GET" and path.startswith("/social-sets") and "media" not in path:
                raise ProviderHTTPError(401, "Typefully rejected that API key.") from exc
            if exc.status == 402 or _is_quota(exc):
                detail = redact(exc.message, self.api_key)
                raise LimitReached(
                    "Typefully's free publishing quota is used up, or the account needs a paid plan "
                    f"before this can publish. {detail} Nothing was posted."
                ) from exc
            if exc.status == 429:
                raise ProviderHTTPError(429, "Typefully's rate limit was hit. Wait a moment and try again.") from exc
            raise


def _quota(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    remaining = raw.get("remaining")
    used = raw.get("used")
    return {
        "used": int(used) if isinstance(used, int) else None,
        "remaining": int(remaining) if isinstance(remaining, int) else None,
        "resets_at": str(raw.get("resets_at") or "") or None,
    }


def _is_quota(exc: ProviderHTTPError) -> bool:
    text = f"{exc.message} {exc.payload}".lower()
    return "quota" in text or "monthly" in text and "limit" in text or "paid plan" in text


def _draft_status(when: str, draft: dict[str, Any]) -> str:
    if when == "now":
        return "publishing"
    raw = str(draft.get("status") or "")
    if raw in {"scheduled", "publishing", "published", "draft"}:
        return raw
    return "queued" if when == "queue" else "scheduled"
