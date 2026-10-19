"""Config-driven lipsync provider adapter (open MuseTalk / LatentSync, async).

One tested :class:`LipsyncAdapter` serves several open lipsync providers that
share the same async shape: POST a job (a source **image_url** + driving
**audio_url**) → get a run id → GET a status until terminal → read the output
mp4 url + produced seconds for usage metering. Each provider is a small
:class:`LipsyncConfig` (base_url, paths, field names, state map, license class);
the differences live in data, not bespoke classes — so MuseTalk and LatentSync
are both *configs* in :data:`LIPSYNC_CONFIGS`, one file, disjoint from the
character (CHAR) providers.

Implements the frozen ``ProviderAdapter`` contract
(``provider_key``/``catalog``/``quote``/``submit``/``poll``/``cancel``/
``normalize_usage``). The HTTP ``request_fn`` is the injectable network seam —
tests pass a fake and assert the real request/response handling; adapter logic
is never stubbed (copies ``sadtalker.py`` + ``async_media.py``). The adapter
NEVER debits wallets, mutates Job rows, or sets a client price.

``submit`` REQUIRES both ``image_url`` and ``audio_url`` — the domain hands it
short-lived presigned GETs against our OWN bucket (SSRF §8), never a raw client
URL. ``poll`` maps the provider status via a state map to the normalized
``RUN_*`` states; ``normalize_usage`` meters whole seconds.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any

from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    ModelListing,
    NormalizedUsage,
    ProviderError,
    ProviderRun,
    QuoteResult,
)
from app.domains.routing.providers._pricing import quote_from_price
from app.domains.routing.providers._transport import build_json_transport

# Provider status vocabularies → normalized run states.
_DEFAULT_STATE_MAP: dict[str, str] = {
    "queued": RUN_QUEUED,
    "pending": RUN_QUEUED,
    "starting": RUN_QUEUED,
    "created": RUN_QUEUED,
    "submitted": RUN_QUEUED,
    "running": RUN_RUNNING,
    "processing": RUN_RUNNING,
    "in_progress": RUN_RUNNING,
    "inferencing": RUN_RUNNING,
    "succeeded": RUN_COMPLETED,
    "success": RUN_COMPLETED,
    "completed": RUN_COMPLETED,
    "complete": RUN_COMPLETED,
    "finished": RUN_COMPLETED,
    "failed": RUN_FAILED,
    "error": RUN_FAILED,
    "canceled": RUN_FAILED,
    "cancelled": RUN_FAILED,
}


@dataclass(frozen=True)
class LipsyncConfig:
    """Static description of one open lipsync provider's async API shape."""

    provider_key: str
    base_url: str
    # License class string (see ``domains.speak.licensing.LicenseClass``). Kept as
    # a plain string here so the routing layer stays free of the speak domain.
    license_class: str = "open_commercial"
    capability: str = "lipsync"
    model_id: str = ""
    submit_path: str = "/run"
    poll_path_tmpl: str = "/status/{id}"  # {id} substituted with the run id
    cancel_path_tmpl: str = "/cancel/{id}"
    id_field: str = "run_id"  # where the run id lives in the submit response
    state_field: str = "status"  # where the status lives in the poll response
    output_field: str = "output_url"  # where the result mp4 url lives
    seconds_field: str = "seconds"  # where the produced seconds live (usage)
    unit: str = "seconds"
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer "
    metering_unit: str = "seconds"
    latency_band: str = "slow"
    state_map: dict = field(default_factory=lambda: dict(_DEFAULT_STATE_MAP))


class LipsyncAdapter:
    """Async lipsync provider adapter parameterized by :class:`LipsyncConfig`."""

    def __init__(
        self,
        config: LipsyncConfig,
        *,
        api_key: str = "",
        request_fn: Any = None,
    ) -> None:
        self._cfg = config
        self._api_key = api_key or os.getenv(
            f"{config.provider_key.upper().replace('-', '_')}_API_KEY", ""
        )
        headers = {
            config.auth_header: f"{config.auth_scheme}{self._api_key}".strip()
        }
        self._request = request_fn or build_json_transport(
            provider_key=config.provider_key,
            base_url=config.base_url,
            headers=headers,
        )

    @property
    def provider_key(self) -> str:
        return self._cfg.provider_key

    @property
    def license_class(self) -> str:
        return self._cfg.license_class

    def catalog(self) -> list[ModelListing]:
        return [
            ModelListing(
                provider_key=self._cfg.provider_key,
                model_id=self._cfg.model_id or f"{self._cfg.provider_key}/lipsync",
                capability=self._cfg.capability,
                metering_unit=self._cfg.metering_unit,
                latency_band=self._cfg.latency_band,
            )
        ]

    def quote(self, request: Any, price_version: Any) -> QuoteResult:
        est = None
        if isinstance(request, dict):
            est = request.get("estimated_seconds") or request.get("estimated_quantity")
        return quote_from_price(price_version, est if est is not None else 5)

    # -- submit ------------------------------------------------------------- #
    def submit(self, request: Any, snapshot: dict, correlation_id: str) -> ProviderRun:
        body = request if isinstance(request, dict) else {}
        # Lipsync needs a source image + driving audio; the domain supplies BOTH
        # as short-lived presigned GETs against our own bucket (never a raw URL).
        if not body.get("image_url") or not body.get("audio_url"):
            raise ProviderError(
                f"{self.provider_key} submit requires image_url + audio_url",
                provider_key=self.provider_key,
                retryable=False,
            )
        payload = self._request(
            "POST",
            self._cfg.submit_path,
            json={
                "image_url": body["image_url"],
                "audio_url": body["audio_url"],
                "correlation_id": correlation_id,
            },
        )
        run_id = _dig(payload, self._cfg.id_field) or payload.get("id")
        if not run_id:
            raise ProviderError(
                f"{self.provider_key} submit returned no {self._cfg.id_field!r}: {payload}",
                provider_key=self.provider_key,
                retryable=False,
            )
        state = self._map_state(_dig(payload, self._cfg.state_field) or "queued")
        return ProviderRun(
            provider_key=self.provider_key,
            run_id=str(run_id),
            state=state,
            raw=payload,
        )

    # -- poll --------------------------------------------------------------- #
    def poll(self, run: ProviderRun) -> ProviderRun:
        if run.is_terminal:
            return run
        path = self._cfg.poll_path_tmpl.format(id=run.run_id)
        payload = self._request("GET", path)
        state = self._map_state(_dig(payload, self._cfg.state_field) or "running")
        result_ref = ""
        usage = None
        if state == RUN_COMPLETED:
            result_ref = _first_url(_dig(payload, self._cfg.output_field))
            usage = self.normalize_usage(payload)
        return ProviderRun(
            provider_key=self.provider_key,
            run_id=run.run_id,
            state=state,
            progress=100 if state == RUN_COMPLETED else int(
                payload.get("progress", run.progress) or run.progress
            ),
            result_ref=result_ref,
            usage=usage,
            raw=payload,
        )

    def cancel(self, run: ProviderRun) -> bool:
        try:
            self._request("POST", self._cfg.cancel_path_tmpl.format(id=run.run_id))
            return True
        except ProviderError:
            return False

    # -- usage -------------------------------------------------------------- #
    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        payload = payload or {}
        raw_seconds = _dig(payload, self._cfg.seconds_field)
        if raw_seconds is None:
            raw_seconds = payload.get("duration", 0)
        try:
            value = float(raw_seconds or 0)
        except (TypeError, ValueError):
            value = 0.0
        # Meter whole seconds, rounding a partial second up (bill for started work).
        seconds = int(value) + (1 if value % 1 else 0)
        return NormalizedUsage(
            unit=self._cfg.unit,
            quantity_units=max(0, seconds),
            cost_micros=0,
            raw=dict(payload),
        )

    def _map_state(self, raw: Any) -> str:
        return self._cfg.state_map.get(str(raw or "").strip().lower(), RUN_RUNNING)


def _dig(payload: Any, dotted: str) -> Any:
    """Read a (possibly dotted) field path from a nested dict."""
    if not isinstance(payload, dict) or not dotted:
        return None
    node: Any = payload
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _first_url(value: Any) -> str:
    """Extract a single result URL from string / list / dict output shapes."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            url = _first_url(item)
            if url:
                return url
        return ""
    if isinstance(value, dict):
        for key in ("url", "video_url", "output_url", "download_url"):
            if value.get(key):
                return str(value[key])
    return ""


# --------------------------------------------------------------------------- #
# Seeded open lipsync provider configs (MuseTalk + LatentSync). Both are configs,
# not bespoke classes. Keys resolved from env at build; base_url overridable.
# --------------------------------------------------------------------------- #
LIPSYNC_CONFIGS: dict[str, LipsyncConfig] = {
    "musetalk": LipsyncConfig(
        provider_key="musetalk",
        base_url="https://musetalk.internal.reelforge.app",
        license_class="open_commercial",
        model_id="musetalk/lipsync",
    ),
    "latentsync": LipsyncConfig(
        provider_key="latentsync",
        base_url="https://latentsync.internal.reelforge.app",
        license_class="source_available",
        model_id="latentsync/lipsync",
    ),
}


def base_url_env(provider_key: str) -> str:
    """Env var that overrides a seeded provider's base URL (``MUSETALK_BASE_URL``)."""
    return f"{str(provider_key or '').strip().upper().replace('-', '_')}_BASE_URL"


def configured_base_url(provider_key: str) -> str:
    """The base URL the adapter will call: the env override, else the seeded default."""
    cfg = LIPSYNC_CONFIGS.get(str(provider_key or "").strip().lower())
    override = os.getenv(base_url_env(provider_key), "").strip().rstrip("/")
    return override or (cfg.base_url if cfg else "")


def build_lipsync_adapter(
    provider_key: str, *, api_key: str = "", request_fn: Any = None
) -> LipsyncAdapter:
    """Build a seeded lipsync adapter by provider key.

    ``<PROVIDER>_BASE_URL`` (for example ``MUSETALK_BASE_URL``, a self-hosted
    MuseTalk endpoint such as a RunPod serverless URL) overrides the seeded
    base URL; unset keeps the default. Raises :class:`ProviderError` for an
    unknown provider so an unconfigured key can never become a live route.
    """
    cfg = LIPSYNC_CONFIGS.get(str(provider_key or "").strip().lower())
    if cfg is not None:
        override = os.getenv(base_url_env(cfg.provider_key), "").strip().rstrip("/")
        if override:
            cfg = replace(cfg, base_url=override)
    if cfg is None:
        raise ProviderError(
            f"no lipsync config for {provider_key!r}",
            provider_key=str(provider_key),
            retryable=False,
        )
    return LipsyncAdapter(cfg, api_key=api_key, request_fn=request_fn)
