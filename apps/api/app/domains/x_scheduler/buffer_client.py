"""Buffer GraphQL client (https://api.buffer.com, Bearer API key).

Official docs (developers.buffer.com): organizations and channels come from
the ``account`` query; posts are ``createPost`` with a public asset URL
(Buffer has no upload endpoint). Free-plan overflows return a typed
``LimitReachedError`` inside a HTTP 200 GraphQL payload.
"""

from __future__ import annotations

from typing import Any

from app.domains.x_scheduler.errors import LimitReached, redact
from app.domains.x_scheduler.http import ProviderHTTPError, Transport, default_transport, request_json

BUFFER_URL = "https://api.buffer.com"
X_SERVICE = "twitter"

_CHANNELS = """
query MenivorXChannels {
  account {
    organizations {
      id
      name
      channels {
        id
        name
        displayName
        service
        isDisconnected
        isLocked
      }
    }
  }
}
""".strip()

_CREATE = """
mutation MenivorCreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id } }
    ... on LimitReachedError { message }
    ... on MutationError { message }
  }
}
""".strip()

# ShareMode values from the Buffer schema: addToQueue, shareNext, shareNow, customScheduled.
MODES = {
    "now": "shareNow",
    "queue": "addToQueue",
    "schedule": "customScheduled",
}


class BufferClient:
    def __init__(self, api_key: str, transport: Transport | None = None) -> None:
        self.api_key = str(api_key or "").strip()
        self._transport = transport or default_transport

    def list_x_channels(self) -> list[dict[str, Any]]:
        data = self._graphql(_CHANNELS, {})
        account = (data or {}).get("account") or {}
        targets: list[dict[str, Any]] = []
        for org in account.get("organizations") or []:
            org_name = str((org or {}).get("name") or "")
            for channel in (org or {}).get("channels") or []:
                if not isinstance(channel, dict):
                    continue
                if str(channel.get("service") or "") != X_SERVICE:
                    continue
                if channel.get("isDisconnected") or channel.get("isLocked"):
                    continue
                channel_id = str(channel.get("id") or "").strip()
                if not channel_id:
                    continue
                label = str(channel.get("displayName") or channel.get("name") or channel_id)
                targets.append({
                    "id": channel_id,
                    "name": label,
                    "handle": str(channel.get("name") or label),
                    "organization": org_name,
                    "service": "x",
                    "provider": "buffer",
                })
        return targets

    def create_post(
        self,
        *,
        channel_id: str,
        text: str,
        asset_url: str,
        kind: str,
        when: str,
        due_at: str | None,
    ) -> dict[str, Any]:
        mode = MODES[when]
        asset = {"image": {"url": asset_url}} if kind == "image" else {"video": {"url": asset_url}}
        payload: dict[str, Any] = {
            "text": text,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": mode,
            "assets": [asset],
        }
        if mode == "customScheduled":
            payload["dueAt"] = due_at
        data = self._graphql(_CREATE, {"input": payload})
        result = (data or {}).get("createPost") or {}
        typename = str(result.get("__typename") or "")
        if typename == "LimitReachedError":
            detail = str(result.get("message") or "").strip()
            extra = f" {detail}" if detail else ""
            raise LimitReached(
                "Buffer's free plan allows 10 scheduled posts per channel, and this "
                f"channel has reached that limit.{extra} Nothing was posted."
            )
        if typename != "PostActionSuccess":
            detail = redact(str(result.get("message") or "Buffer could not create the post."), self.api_key)
            raise ProviderHTTPError(422, detail or "Buffer could not create the post.", result)
        post = result.get("post") or {}
        return {"id": str(post.get("id") or ""), "status": _status(when)}

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderHTTPError(401, "Buffer API key is missing.")
        try:
            parsed = request_json(
                self._transport,
                "POST",
                BUFFER_URL,
                {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                {"query": query, "variables": variables},
                secret=self.api_key,
            )
        except ProviderHTTPError as exc:
            if exc.status in (401, 403):
                raise ProviderHTTPError(401, "Buffer rejected that API key.") from exc
            raise
        if not isinstance(parsed, dict):
            raise ProviderHTTPError(502, "Buffer returned an unreadable response.")
        errors = parsed.get("errors") or []
        if errors and not parsed.get("data"):
            message = ""
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                message = str(errors[0].get("message") or "")
            lowered = message.lower()
            if "unauth" in lowered or "api key" in lowered or "not authorized" in lowered:
                raise ProviderHTTPError(401, "Buffer rejected that API key.")
            raise ProviderHTTPError(502, redact(message or "Buffer could not complete that request.", self.api_key))
        data = parsed.get("data")
        return data if isinstance(data, dict) else {}


def _status(when: str) -> str:
    if when == "now":
        return "publishing"
    if when == "queue":
        return "queued"
    return "scheduled"
