"""Railyard ABACUS client (Python mirror of ``railyard/abacus.ts``).

Abacus is an optional front-end to Relay that enforces a per-key spend cap
before proxying an OpenAI-shaped chat request upstream. It only makes sense to
stack in front of Relay when the Abacus deployment's ``UPSTREAM_BASE_URL`` points
at Relay; otherwise use :mod:`relay` directly.

Contract::

    POST {ABACUS_URL}/v1/proxy
    Headers:
      X-API-Key:      <ABACUS_API_KEY>
      X-Abacus-Agent: agent_<id>            (per-key identity — the thing capped)
      Authorization:  Bearer <provider-key> (the upstream provider credential)
      X-Request-Id:   <idempotency key>
    Body: a verbatim OpenAI chat.completions request
    Success:   { "success": true, "data": <openai response> }  → we UNWRAP `.data`
    Cap breach: HTTP 402                                        → stop using key

Entirely OPT-IN and never a silent failure: a cap breach surfaces as
``RailyardError(code="cap_exceeded")`` so the caller drops that key and falls
back. API keys are never logged.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Tuple

from .config import (
    RAILYARD_HTTP_TIMEOUT_S,
    AbacusConfig,
    RailyardEnv,
    get_abacus_config,
)
from .errors import RailyardError, truncate_detail

# Transport: ``(url, headers, json_body, timeout_s) -> (status_code, parsed_json)``.
# Injected so the client is fully testable without network access.
RequestFn = Callable[[str, Mapping[str, str], dict, float], Tuple[int, dict]]


def _default_transport(url: str, headers: Mapping[str, str], body: dict, timeout_s: float) -> Tuple[int, dict]:
    """Lazy httpx-backed transport (import-safe; raises only when used)."""
    try:
        import httpx
    except Exception as exc:  # pragma: no cover - exercised only without httpx
        raise RailyardError(
            "httpx is required for the default Abacus transport",
            service="abacus",
            code="transport_error",
        ) from exc
    try:
        resp = httpx.post(url, headers=dict(headers), json=body, timeout=timeout_s)
    except Exception as exc:  # network error
        raise RailyardError(
            f"Abacus request failed: {exc}",
            service="abacus",
            code="http_error",
        ) from exc
    try:
        parsed = resp.json()
    except Exception:
        parsed = {}
    return resp.status_code, (parsed if isinstance(parsed, dict) else {})


def _format_agent_header(agent_id: str) -> str:
    """Normalize an agent id to the ``agent_<id>`` form Abacus expects."""
    return agent_id if agent_id.startswith("agent_") else f"agent_{agent_id}"


@dataclass(frozen=True)
class AbacusClient:
    """A per-call Abacus proxy. Construction never throws; the gate is enforced
    per-call (an unconfigured or capped key raises :class:`RailyardError`)."""

    config: AbacusConfig
    request_fn: RequestFn = _default_transport

    @property
    def configured(self) -> bool:
        return self.config.configured

    def proxy_chat(
        self,
        body: dict,
        *,
        provider_key: str,
        agent_id: Optional[str] = None,
        request_id: Optional[str] = None,
        timeout_s: float = RAILYARD_HTTP_TIMEOUT_S,
    ) -> dict:
        """Proxy a verbatim OpenAI chat body through the per-key cap.

        Returns the unwrapped OpenAI response dict. Raises ``RailyardError``:
        ``not_configured`` (Abacus off or missing agent/provider key),
        ``cap_exceeded`` (HTTP 402), or ``bad_response``.
        """
        if not self.config.configured or not self.config.api_key:
            raise RailyardError(
                "Abacus is not configured", service="abacus", code="not_configured"
            )
        resolved_agent = agent_id or self.config.agent_id
        if not resolved_agent:
            raise RailyardError(
                "Abacus requires an agent id (agent_id / ABACUS_AGENT_ID)",
                service="abacus",
                code="not_configured",
            )
        if not provider_key:
            raise RailyardError(
                "Abacus requires an upstream provider_key",
                service="abacus",
                code="not_configured",
            )

        endpoint = "/v1/proxy"
        req_id = request_id or f"reelforge-{int(time.time() * 1000)}-{random.randint(0, 1_000_000):06d}"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.config.api_key,
            "X-Abacus-Agent": _format_agent_header(resolved_agent),
            "Authorization": f"Bearer {provider_key}",
            "X-Request-Id": req_id,
        }
        url = f"{self.config.base_url}{endpoint}"

        status, data = self.request_fn(url, headers, body, timeout_s)

        if status == 402:
            raise RailyardError(
                "Abacus per-key spend cap exceeded (HTTP 402)",
                service="abacus",
                code="cap_exceeded",
                status=402,
                endpoint=endpoint,
                detail=truncate_detail(data.get("error") or data.get("message") or "cap exceeded"),
            )

        # Success envelope: { success: true, data: <openai response> } → unwrap.
        inner = data.get("data")
        if data.get("success") is not True or not isinstance(inner, dict):
            raise RailyardError(
                "Abacus response was not a success envelope",
                service="abacus",
                code="bad_response",
                status=status,
                endpoint=endpoint,
                detail=truncate_detail(data.get("error") or data.get("message") or str(data)[:200]),
            )
        return inner


def create_abacus_client(
    *,
    env: Optional[RailyardEnv] = None,
    request_fn: Optional[RequestFn] = None,
) -> AbacusClient:
    """Build an Abacus client bound to the given env. Never throws."""
    config = get_abacus_config(env)
    return AbacusClient(config=config, request_fn=request_fn or _default_transport)
