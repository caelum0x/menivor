"""Routing domain service: resolve a provider/model route + record usage.

Worker-internal (no HTTP). Composes the reviewed catalog (candidates + active
prices) with the pure routing policy and the provider registry to produce a
concrete, ordered route whose primary is the caller-selected model and whose
fallbacks (only with consent) are equivalent, in-budget alternatives. Also
normalizes and persists provider usage into ``usage_records`` for reconciliation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)

from loguru import logger
from sqlalchemy.orm import Session

from app.domains.catalog import policy as catalog_policy
from app.domains.catalog.repository import CatalogRepository
from app.domains.routing.base import (
    RUN_COMPLETED,
    NormalizedUsage,
    ProviderError,
    ProviderRegistry,
    ProviderRun,
    registry as default_registry,
)
from app.domains.routing.policy import Candidate, RoutePolicy, select_route
from app.models.db.marketplace import UsageRecord


class RoutingError(Exception):
    """No admissible route / no registered adapter for the requested capability."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class ResolvedRoute:
    """The concrete route for one job stage: an ordered candidate list.

    ``order[0]`` is the primary (caller-selected) model; the remainder are the
    consented, in-budget fallbacks. ``adapters`` maps each candidate's provider
    to its registered adapter so the worker never imports an SDK directly.
    """

    def __init__(
        self,
        *,
        capability: str,
        order: list[Candidate],
        adapters: dict[str, object],
        advice: object | None = None,
    ) -> None:
        self.capability = capability
        self.order = order
        self.adapters = adapters
        # The model-advisor verdict when the primary was AI-picked (else None for
        # an explicit caller pin). Carries source/confidence/degraded provenance.
        self.advice = advice

    @property
    def primary(self) -> Candidate:
        return self.order[0]

    @property
    def fallbacks(self) -> list[Candidate]:
        return self.order[1:]

    def to_dict(self) -> dict:
        return {
            "capability": self.capability,
            "primary_model_id": self.primary.model_id,
            "primary_provider_key": self.primary.provider_key,
            "price_version_id": self.primary.price_version_id,
            "route": [
                {
                    "model_id": c.model_id,
                    "provider_key": c.provider_key,
                    "est_cost_micros": c.est_cost_micros,
                    "price_version_id": c.price_version_id,
                }
                for c in self.order
            ],
            "advice": self.advice.to_record() if self.advice is not None else None,
        }


class RoutingService:
    """Route resolution + usage normalization over one DB session."""

    def __init__(
        self, session: Session, *, provider_registry: ProviderRegistry | None = None
    ) -> None:
        self._session = session
        self._catalog = CatalogRepository(session)
        self._registry = provider_registry or default_registry

    # ------------------------------------------------------------------ #
    # Route resolution
    # ------------------------------------------------------------------ #
    def _build_candidates(
        self,
        capability: str,
        *,
        estimated_quantity: int | None,
        include_shadow: bool,
        at: datetime | None,
    ) -> list[Candidate]:
        """Build routing candidates from live catalog entries + active prices."""
        entries = self._catalog.list_models(
            capability=capability, include_shadow=include_shadow, limit=200
        )
        provider_ids = {e.provider_id for e in entries}
        providers = self._catalog.providers_by_ids(provider_ids)
        candidates: list[Candidate] = []
        for entry in entries:
            price = self._catalog.active_price_version(entry.model_id, at=at)
            if price is None:
                # No active price -> not routable; skip rather than mis-quote.
                continue
            quantity = catalog_policy.estimate_quantity(
                price.quote_rules, estimated_quantity
            )
            est_cost = catalog_policy.stage_cost_micros(
                unit_price_micros=price.unit_price_micros,
                quantity_units=quantity,
                min_charge_micros=price.min_charge_micros,
                flat_fee_micros=price.flat_fee_micros,
            )
            provider = providers.get(entry.provider_id)
            candidates.append(
                Candidate(
                    model_id=entry.model_id,
                    provider_key=getattr(provider, "provider_key", ""),
                    capability=entry.capability,
                    est_cost_micros=est_cost,
                    region=entry.region,
                    availability_state=entry.availability_state,
                    latency_band=entry.latency_band,
                    price_version_id=price.id,
                    health_state=getattr(provider, "health_state", "unknown") or "unknown",
                )
            )
        return candidates

    def resolve_route(
        self,
        *,
        capability: str,
        model_id: str = "",
        policy: RoutePolicy | None = None,
        estimated_quantity: int | None = None,
        include_shadow: bool = False,
        at: datetime | None = None,
        brief: object | None = None,
        advisor_client: object | None = None,
    ) -> ResolvedRoute:
        """Resolve the caller-selected model into an ordered, adapter-backed route.

        When ``model_id`` is given it is the primary (an explicit caller pin; the
        advisor is never consulted). When it is omitted and a ``brief`` is supplied,
        the model advisor PICKS the primary from the admissible candidates — a typed
        Choice that degrades to the deterministic cost/latency policy pick when no
        ``TYPESAFE_API_KEY`` / client is available (never a fabricated pick). The
        resulting :class:`~app.domains.routing.model_advisor.AdvisorChoice` is
        attached to the route as ``advice`` for the record/UI.

        Raises :class:`RoutingError` (422) when no admissible route exists or the
        primary provider has no registered adapter. Fallbacks whose provider has
        no adapter are dropped (never a silent unrouted substitution).
        """
        policy = policy or RoutePolicy()
        # OpenRouter-style variant suffix: ``…:nitro`` (fastest) / ``…:floor``
        # (cheapest) sets the sort strategy and opts into equivalent fallback so
        # the best provider for the capability is chosen.
        from dataclasses import replace

        from app.domains.routing.policy import (
            FALLBACK_EQUIVALENT,
            resolve_variant,
        )

        model_id, variant_sort = resolve_variant(model_id)
        if variant_sort is not None:
            policy = replace(
                policy,
                sort=policy.sort or variant_sort,
                fallback=policy.fallback if policy.wants_fallback() else FALLBACK_EQUIVALENT,
            )

        candidates = self._build_candidates(
            capability,
            estimated_quantity=estimated_quantity,
            include_shadow=include_shadow,
            at=at,
        )

        # AI-picked primary: only when the caller did not pin a model and passed a
        # brief to judge. The pick is trusted over the policy only when confident
        # and admissible; otherwise (or with no key/client) it degrades to the
        # deterministic cost/latency policy pick — the advisor never breaks routing.
        advice = None
        if not model_id and brief is not None:
            from app.domains.routing.model_advisor import advise_primary_sync

            advice = advise_primary_sync(
                brief, candidates, policy=policy, client=advisor_client
            )
            model_id = advice.model_id

        ordered = select_route(model_id, candidates, policy)
        if not ordered:
            raise RoutingError(
                422,
                f"no admissible route for '{model_id}' ({capability})",
            )

        # Keep only candidates backed by a registered adapter; the primary must
        # have one or the request cannot be served.
        adapters: dict[str, object] = {}
        routable: list[Candidate] = []
        for cand in ordered:
            adapter = self._registry.get(cand.provider_key)
            if adapter is None:
                continue
            adapters[cand.provider_key] = adapter
            routable.append(cand)

        if not routable or routable[0].model_id != ordered[0].model_id:
            raise RoutingError(
                422,
                f"no registered provider adapter for primary route '{model_id}'",
            )
        return ResolvedRoute(
            capability=capability, order=routable, adapters=adapters, advice=advice
        )

    # ------------------------------------------------------------------ #
    # Usage recording (reconciliation)
    # ------------------------------------------------------------------ #
    def persist_usage(
        self,
        *,
        normalized: NormalizedUsage,
        job_id: str | None = None,
        account_id: str | None = None,
        stage: str = "",
        model_id: str = "",
        provider_key: str = "",
        price_version_id: str = "",
        correlation_id: str = "",
    ) -> UsageRecord:
        """Persist a normalized provider usage row for later reconciliation."""
        record = UsageRecord(
            job_id=job_id,
            account_id=account_id,
            stage=stage,
            model_id=model_id,
            provider_key=provider_key,
            price_version_id=price_version_id,
            unit=normalized.unit,
            quantity_units=int(normalized.quantity_units),
            cost_micros=int(normalized.cost_micros),
            currency=normalized.currency,
            correlation_id=correlation_id,
            raw_usage=dict(normalized.raw or {}),
        )
        self._session.add(record)
        self._session.flush()
        return record

    # ------------------------------------------------------------------ #
    # Execution engine (Phase M1) — submit -> poll -> price -> record
    # ------------------------------------------------------------------ #
    def _price_usage_micros(
        self, model_id: str, price_version_id: str, usage: NormalizedUsage | None
    ) -> int:
        """Price normalized usage from OUR resolved price version (never adapter's).

        Prefers the exact stored ``price_version_id``; falls back to the model's
        active price. Returns 0 when neither the price nor usage is available.
        """
        if usage is None:
            return 0
        price = self._catalog.get_price_version(price_version_id) or (
            self._catalog.active_price_version(model_id)
        )
        if price is None:
            return 0
        return catalog_policy.stage_cost_micros(
            unit_price_micros=int(price.unit_price_micros or 0),
            quantity_units=int(usage.quantity_units or 0),
            min_charge_micros=int(price.min_charge_micros or 0),
            flat_fee_micros=int(price.flat_fee_micros or 0),
        )

    def _drive_adapter(
        self,
        adapter: Any,
        candidate: Candidate,
        request: dict,
        *,
        correlation_id: str,
        max_poll_attempts: int,
        sleep_fn: Callable[[float], None],
        poll_interval_s: float,
    ) -> ProviderRun:
        """Submit to one adapter and poll to a terminal state (bounded)."""
        snapshot = {
            "model_id": candidate.model_id,
            "provider_key": candidate.provider_key,
            "price_version_id": candidate.price_version_id,
        }
        run = adapter.submit(request, snapshot, correlation_id)
        attempts = 0
        while not run.is_terminal and attempts < max_poll_attempts:
            sleep_fn(poll_interval_s)
            run = adapter.poll(run)
            attempts += 1
        return run

    def execute(
        self,
        route: "ResolvedRoute",
        request: dict,
        *,
        correlation_id: str = "",
        stage: str = "",
        job_id: str | None = None,
        account_id: str | None = None,
        max_poll_attempts: int = 60,
        poll_interval_s: float = 2.0,
        sleep_fn: Callable[[float], None] | None = None,
        adapter_overrides: dict | None = None,
        byok_providers: set | None = None,
        health_recorder: Callable[..., None] | None = None,
    ) -> "ExecutionResult":
        """Run a resolved route: submit -> poll -> price -> record usage.

        Advances to the next candidate ONLY on a retryable ``ProviderError`` or a
        terminal ``failed`` run (i.e. consented fallback the route already
        contains). A non-retryable ``ProviderError`` fails hard. Exhausting the
        route raises :class:`RoutingError` (502). On success it prices the usage
        from OUR price version, persists a ``usage_records`` row, and returns the
        result.

        ``adapter_overrides`` (BYOK) maps ``provider_key -> adapter``; when set for
        a candidate's provider that adapter (bound to the customer's own key) is
        used instead of the platform registry adapter.
        """
        sleep = sleep_fn if sleep_fn is not None else (lambda _s: None)
        overrides = adapter_overrides or {}
        byok_providers = byok_providers if byok_providers is not None else set(overrides)
        record_health = health_recorder if health_recorder is not None else (
            lambda *_a, **_k: None
        )
        last_error: Exception | None = None

        for candidate in route.order:
            adapter = overrides.get(candidate.provider_key) or route.adapters.get(
                candidate.provider_key
            )
            if adapter is None:
                continue
            started = time.monotonic()
            try:
                run = self._drive_adapter(
                    adapter,
                    candidate,
                    request,
                    correlation_id=correlation_id,
                    max_poll_attempts=max_poll_attempts,
                    sleep_fn=sleep,
                    poll_interval_s=poll_interval_s,
                )
            except ProviderError as exc:
                last_error = exc
                record_health(candidate.provider_key, False, _elapsed_ms(started), candidate.capability)
                if not exc.retryable:
                    # A hard provider error is not a fallback trigger.
                    raise RoutingError(502, f"provider error: {exc}") from exc
                logger.warning(
                    f"route candidate {candidate.model_id} retryable failure: {exc}"
                )
                continue

            if run.state != RUN_COMPLETED:
                last_error = RuntimeError(f"run ended {run.state}")
                record_health(candidate.provider_key, False, _elapsed_ms(started), candidate.capability)
                logger.warning(
                    f"route candidate {candidate.model_id} ended {run.state}; "
                    f"trying fallback if any"
                )
                continue

            record_health(candidate.provider_key, True, _elapsed_ms(started), candidate.capability)

            usage = run.usage or (
                adapter.normalize_usage((run.raw or {}).get("usage", {}))
                if hasattr(adapter, "normalize_usage")
                else None
            )
            provider_cost = self._price_usage_micros(
                candidate.model_id, candidate.price_version_id, usage
            )
            # BYOK: the customer paid the provider directly, so ReelForge charges a
            # disclosed routing fee instead of the pass-through provider price.
            if candidate.provider_key in byok_providers:
                from app.domains.spend import policy as spend_policy

                cost_micros = spend_policy.byok_fee_micros(provider_cost)
            else:
                cost_micros = provider_cost
            usage_record_id = ""
            if usage is not None:
                priced = NormalizedUsage(
                    unit=usage.unit,
                    quantity_units=usage.quantity_units,
                    cost_micros=cost_micros,
                    currency=usage.currency,
                    raw=usage.raw,
                )
                record = self.persist_usage(
                    normalized=priced,
                    job_id=job_id,
                    account_id=account_id,
                    stage=stage,
                    model_id=candidate.model_id,
                    provider_key=candidate.provider_key,
                    price_version_id=candidate.price_version_id,
                    correlation_id=correlation_id,
                )
                usage_record_id = record.id
            return ExecutionResult(
                run=run,
                candidate=candidate,
                usage=usage,
                cost_micros=cost_micros,
                usage_record_id=usage_record_id,
            )

        raise RoutingError(
            502, f"all route candidates failed (last: {last_error})"
        )


@dataclass
class ExecutionResult:
    """The outcome of running one resolved route through a provider."""

    run: ProviderRun
    candidate: Candidate
    usage: NormalizedUsage | None
    cost_micros: int
    usage_record_id: str = ""

    @property
    def model_id(self) -> str:
        return self.candidate.model_id

    @property
    def provider_key(self) -> str:
        return self.candidate.provider_key

    @property
    def result_ref(self) -> str:
        return self.run.result_ref
