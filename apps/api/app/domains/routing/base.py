"""Provider adapter contract + normalized transport types + a registry.

Every upstream (Anthropic, ElevenLabs, HeyGen, Comfy/Pixelle, OpenRouter, …)
conforms to one internal :class:`ProviderAdapter` protocol
(PROVIDER_MARKETPLACE_PLAN.md §5). Adapters own outbound calls only:

    catalog() -> reviewed ModelListing[]
    quote(request, price_version) -> QuoteResult (max_cost + expiry)
    submit(request, snapshot, correlation_id) -> ProviderRun
    poll(run) -> ProviderRun (state/progress/normalized usage)
    cancel(run) -> best-effort bool
    normalize_usage(payload) -> NormalizedUsage

They must never debit wallets, mutate job rows, or set the client price — the
wallet/reels domains own those transactions. Normalized DTOs are frozen so an
adapter can never hand a caller a mutable, provider-shaped object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

# Terminal + in-flight run states, normalized across providers.
RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_CANCELED = "canceled"
TERMINAL_STATES = frozenset({RUN_COMPLETED, RUN_FAILED, RUN_CANCELED})


class ProviderError(Exception):
    """Normalized provider failure with an explicit retry hint.

    Adapters raise this (never a raw SDK/HTTP error) so the routing/worker layer
    can decide retry vs. fallback vs. fail without knowing provider internals.
    """

    def __init__(
        self, message: str, *, provider_key: str = "", retryable: bool = False
    ) -> None:
        super().__init__(message)
        self.provider_key = provider_key
        self.retryable = retryable


@dataclass(frozen=True)
class ModelListing:
    """A reviewed model a provider can serve, in normalized form."""

    provider_key: str
    model_id: str
    capability: str
    metering_unit: str = ""
    region: str = ""
    availability_state: str = "available"
    latency_band: str = ""


@dataclass(frozen=True)
class QuoteResult:
    """A provider's max cost for a request against a resolved price version."""

    max_cost_micros: int
    expires_at: datetime
    price_version_id: str = ""
    currency: str = "USD"


@dataclass(frozen=True)
class ProviderRun:
    """A submitted provider job's normalized state snapshot."""

    provider_key: str
    run_id: str
    state: str = RUN_QUEUED
    progress: int = 0
    result_ref: str = ""
    usage: "NormalizedUsage | None" = None
    raw: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


@dataclass(frozen=True)
class NormalizedUsage:
    """Provider-reported usage normalized to a unit + integer-micro cost."""

    unit: str
    quantity_units: int
    cost_micros: int
    currency: str = "USD"
    raw: dict = field(default_factory=dict)


@runtime_checkable
class ProviderAdapter(Protocol):
    """The single outbound contract every reviewed provider implements."""

    @property
    def provider_key(self) -> str: ...

    def catalog(self) -> list[ModelListing]: ...

    def quote(self, request: Any, price_version: Any) -> QuoteResult: ...

    def submit(
        self, request: Any, snapshot: dict, correlation_id: str
    ) -> ProviderRun: ...

    def poll(self, run: ProviderRun) -> ProviderRun: ...

    def cancel(self, run: ProviderRun) -> bool: ...

    def normalize_usage(self, payload: dict) -> NormalizedUsage: ...


class ProviderRegistry:
    """A process-local registry of reviewed provider adapters keyed by name.

    There is exactly one source of the outbound protocol code; the routing
    service resolves adapters through this registry rather than importing SDKs
    directly. Registration is idempotent-by-key (last registration wins) so a
    reviewed adapter can be swapped in tests without leaking global state.
    """

    def __init__(self) -> None:
        self._by_key: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        key = getattr(adapter, "provider_key", "")
        if not key:
            raise ValueError("provider adapter must expose a non-empty provider_key")
        self._by_key[key] = adapter

    def unregister(self, provider_key: str) -> None:
        self._by_key.pop(provider_key, None)

    def get(self, provider_key: str) -> ProviderAdapter | None:
        return self._by_key.get(provider_key)

    def has(self, provider_key: str) -> bool:
        return provider_key in self._by_key

    def keys(self) -> list[str]:
        return sorted(self._by_key)

    def clear(self) -> None:
        self._by_key.clear()


# Process-wide default registry. Tests construct their own to stay isolated.
registry = ProviderRegistry()
