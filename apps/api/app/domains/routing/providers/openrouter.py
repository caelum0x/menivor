"""OpenRouter gateway adapter (one reviewed upstream provider).

OpenRouter is treated as a single upstream *provider gateway* under ReelForge's
own catalog/routing/wallet contract (PROVIDER_MARKETPLACE_PLAN.md §9.2), never a
replacement for it. This adapter implements the routing ``ProviderAdapter``
protocol for text/script generation and owns outbound calls only — it never
debits wallets, mutates jobs, or sets the client price.

The HTTP transport is injected (``request_fn``) so the adapter is fully testable
without network access; the default transport lazily builds an ``httpx`` client
and is import-safe (a missing ``httpx`` degrades to a clear runtime error, never
an ImportError at startup).
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping, Optional

from app.core.money import usd_to_micros
from app.domains.routing.base import (
    RUN_COMPLETED,
    ModelListing,
    NormalizedUsage,
    ProviderError,
    ProviderRun,
    QuoteResult,
)
from app.domains.catalog import policy as catalog_policy

# The transport is any callable ``(method, path, *, json=None) -> dict``.
RequestFn = Callable[..., dict]

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_PROVIDER_KEY = "openrouter"
_DEFAULT_TIMEOUT_S = 60


def _default_transport(base_url: str, api_key: str, timeout_s: int) -> RequestFn:
    """Build a lazy httpx-backed transport (import-safe; raises only when used)."""

    def _request(method: str, path: str, *, json: dict | None = None) -> dict:
        try:
            import httpx
        except Exception as exc:  # pragma: no cover - exercised only without httpx
            raise ProviderError(
                "httpx is required for the default OpenRouter transport",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            ) from exc
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # OpenRouter attribution headers (optional but recommended).
            "HTTP-Referer": os.getenv("REELFORGE_OPENROUTER_REFERER", "https://reelforge.app"),
            "X-Title": os.getenv("REELFORGE_OPENROUTER_TITLE", "ReelForge"),
        }
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            resp = httpx.request(
                method, url, headers=headers, json=json, timeout=timeout_s
            )
        except Exception as exc:  # network error -> retryable
            raise ProviderError(
                f"OpenRouter request failed: {exc}",
                provider_key=_PROVIDER_KEY,
                retryable=True,
            ) from exc
        if resp.status_code >= 500:
            raise ProviderError(
                f"OpenRouter server error {resp.status_code}",
                provider_key=_PROVIDER_KEY,
                retryable=True,
            )
        if resp.status_code >= 400:
            raise ProviderError(
                f"OpenRouter client error {resp.status_code}: {resp.text[:200]}",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        return resp.json()

    return _request


class OpenRouterAdapter:
    """A routing ``ProviderAdapter`` for OpenRouter-gatewayed text generation."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        request_fn: RequestFn | None = None,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
        railyard_env: Optional[Mapping[str, Optional[str]]] = None,
        railyard_chat_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        # Railyard hop (Abacus cap, then Relay) for chat completions. Opt-in:
        # with no RELAY_URL / RAILYARD_RELAY_URL / ABACUS_* set, submit() goes
        # straight to OpenRouter exactly as before. ``railyard_env`` and
        # ``railyard_chat_fn`` are injectable for tests.
        self._railyard_env = railyard_env
        self._railyard_chat_fn = railyard_chat_fn
        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self._base_url = base_url or os.getenv(
            "OPENROUTER_BASE_URL", _DEFAULT_BASE_URL
        )
        self._request = request_fn or _default_transport(
            self._base_url, self._api_key, timeout_s
        )

    @property
    def provider_key(self) -> str:
        return _PROVIDER_KEY

    # ------------------------------------------------------------------ #
    # Catalog
    # ------------------------------------------------------------------ #
    def raw_models(self) -> list[dict]:
        """Return OpenRouter's raw ``/models`` rows (id, name, pricing, …).

        Used by the catalog importer to ingest pricing/modality metadata that the
        normalized :class:`ModelListing` intentionally omits.
        """
        payload = self._request("GET", "/models")
        return list(payload.get("data", []) or [])

    def catalog(self) -> list[ModelListing]:
        """List OpenRouter models mapped to reviewed ReelForge script listings.

        Only the normalized shape is returned; admission to the product catalog
        (pricing, availability, release status) is an operator decision, not this
        adapter's — it merely reports what the gateway can serve.
        """
        listings: list[ModelListing] = []
        for row in self.raw_models():
            model_id = str(row.get("id") or "").strip()
            if not model_id:
                continue
            listings.append(
                ModelListing(
                    provider_key=_PROVIDER_KEY,
                    # Namespaced ReelForge catalog id so provider ids never leak raw.
                    model_id=f"openrouter/{model_id}",
                    capability="script",
                    metering_unit="tokens",
                )
            )
        return listings

    # ------------------------------------------------------------------ #
    # Quote
    # ------------------------------------------------------------------ #
    def quote(self, request: Any, price_version: Any) -> QuoteResult:
        """Max-cost quote from OUR price version + the request's token estimate.

        The adapter never invents a price: it uses the ReelForge-resolved
        ``price_version`` and the estimated quantity to bound the spend, mirroring
        the catalog quote math so a route quote and a catalog quote agree.
        """
        estimated = None
        if isinstance(request, dict):
            estimated = request.get("estimated_quantity")
        quantity = catalog_policy.estimate_quantity(
            getattr(price_version, "quote_rules", {}) or {}, estimated
        )
        max_cost = catalog_policy.stage_cost_micros(
            unit_price_micros=int(getattr(price_version, "unit_price_micros", 0) or 0),
            quantity_units=quantity,
            min_charge_micros=int(getattr(price_version, "min_charge_micros", 0) or 0),
            flat_fee_micros=int(getattr(price_version, "flat_fee_micros", 0) or 0),
        )
        return QuoteResult(
            max_cost_micros=max_cost,
            expires_at=catalog_policy.quote_expiry(),
            price_version_id=str(getattr(price_version, "id", "") or ""),
        )

    # ------------------------------------------------------------------ #
    # Submit / poll / cancel (chat completions are synchronous)
    # ------------------------------------------------------------------ #
    def _raw_model_id(self, snapshot: dict) -> str:
        """Recover the upstream model id from a ``openrouter/<id>`` catalog id."""
        model_id = str(snapshot.get("model_id", "") or "")
        return model_id[len("openrouter/") :] if model_id.startswith("openrouter/") else model_id

    def submit(
        self, request: Any, snapshot: dict, correlation_id: str
    ) -> ProviderRun:
        """Run a chat completion and return a terminal, usage-bearing run.

        OpenRouter chat completions are synchronous, so the returned run is
        already ``completed`` (or raises :class:`ProviderError`); :meth:`poll`
        simply echoes it.
        """
        messages = []
        if isinstance(request, dict):
            messages = request.get("messages") or []
        body = {"model": self._raw_model_id(snapshot), "messages": messages}
        payload = self._railyard_payload(body, correlation_id)
        if payload is None:
            from app.integrations.railyard.provider_clients import relay_only

            if relay_only():  # Wave P PM1.5: production LLM calls go through Relay only
                raise ProviderError("Relay is required for LLM calls (RAILYARD_LIVE=1) and did not answer",
                                    provider_key=_PROVIDER_KEY, retryable=True)
            payload = self._request("POST", "/chat/completions", json=body)
        usage = self.normalize_usage(payload.get("usage", {}) or {})
        choices = payload.get("choices") or []
        text = ""
        if choices:
            text = str((choices[0].get("message") or {}).get("content", "") or "")
        return ProviderRun(
            provider_key=_PROVIDER_KEY,
            run_id=str(payload.get("id", "") or correlation_id or "openrouter-run"),
            state=RUN_COMPLETED,
            progress=100,
            result_ref=text,
            usage=usage,
            raw=payload,
        )

    def _railyard_payload(self, body: dict, correlation_id: str) -> dict | None:
        """Serve ``body`` through Railyard when configured, else ``None``.

        A spend cap or rate limit from Abacus/Relay is a hard stop surfaced as a
        non-retryable :class:`ProviderError`; it is never routed around through
        uncapped direct OpenRouter spend. Any other Railyard failure returns
        ``None`` so the direct path runs.
        """
        from app.domains.railyard.chat_payload import HARD_STOP_CODES, run_chat_payload
        from app.domains.railyard.errors import RailyardError
        from app.domains.railyard.llm_gateway import railyard_llm_enabled
        from app.integrations.railyard import meter_llm_call, relay_env

        env = relay_env(self._railyard_env)
        if not railyard_llm_enabled(env):
            return None
        chat = self._railyard_chat_fn or run_chat_payload
        try:
            routed = chat(
                body,
                relay_provider=_PROVIDER_KEY,
                provider_api_key=self._api_key,
                request_id=correlation_id or None,
                env=env,
            )
        except RailyardError as error:
            if error.code in HARD_STOP_CODES:
                raise ProviderError(
                    f"Railyard {error.service} stopped this request ({error.code})",
                    provider_key=_PROVIDER_KEY,
                    retryable=False,
                ) from error
            return None
        if routed is None:
            return None
        payload = routed.payload
        choices = payload.get("choices") or []
        completion = ""
        if choices:
            completion = str((choices[0].get("message") or {}).get("content", "") or "")
        meter_llm_call(
            model=str(body.get("model", "")),
            provider=_PROVIDER_KEY,
            prompt_chars=sum(len(str(m.get("content", "") or "")) for m in body.get("messages") or [] if isinstance(m, dict)),
            completion_chars=len(completion),
            routed_via=routed.routed_via,
            request_id=correlation_id or None,
            env=self._railyard_env,
        )
        return payload

    def poll(self, run: ProviderRun) -> ProviderRun:
        # Synchronous provider: the run is already terminal at submit time.
        return run

    def cancel(self, run: ProviderRun) -> bool:
        # Nothing to cancel for a synchronous completion.
        return False

    # ------------------------------------------------------------------ #
    # Usage normalization
    # ------------------------------------------------------------------ #
    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        """Map an OpenRouter ``usage`` block to normalized tokens + micro-cost.

        Prefers OpenRouter's reported ``cost`` (USD) when present; otherwise the
        cost is left at 0 for the domain to price from the resolved price version.
        """
        payload = payload or {}
        total = int(payload.get("total_tokens", 0) or 0)
        if not total:
            total = int(payload.get("prompt_tokens", 0) or 0) + int(
                payload.get("completion_tokens", 0) or 0
            )
        cost_micros = 0
        raw_cost = payload.get("cost")
        if raw_cost is not None:
            try:
                cost_micros = usd_to_micros(raw_cost)
            except ValueError:
                cost_micros = 0
        return NormalizedUsage(
            unit="tokens",
            quantity_units=total,
            cost_micros=cost_micros,
            raw=dict(payload),
        )
