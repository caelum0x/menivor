"""Generation runtime seam: resolve a route, run it, record the actual cost.

Ties the routing execution engine (Phase M1) to the wallet job marker so a
metered provider run settles at its real cost. Worker-internal. Also exposes
``ensure_adapters_registered`` — a launch-flag-gated, credential-gated startup
hook that populates the provider registry (never at import time).
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.domains.routing.policy import RoutePolicy
from app.domains.routing.service import ExecutionResult, RoutingService


def _byok_resolver_for(session, user_id: str, use_byok: bool):
    """Build a ``provider_key -> secret|None`` BYOK resolver, or None.

    BYOK is gated on explicit consent: even when a job requests ``use_byok`` and
    a key is stored, the customer's key is only used when their spend policy has
    ``byok_allowed`` set. Absent the spend layer, consent defaults to off.
    """
    if not (use_byok and user_id):
        return None
    try:
        from app.domains.spend.service import SpendPolicyService

        if not SpendPolicyService(session).byok_allowed(user_id):
            return None
    except Exception:  # noqa: BLE001 - no consent record -> no BYOK
        return None
    from app.domains.byok.service import BYOKService

    svc = BYOKService(session)
    return lambda pk: svc.resolve_secret(user_id, pk)


def _byok_overrides(route, byok_resolver) -> dict:
    """Build per-provider adapter overrides bound to customer BYOK keys."""
    overrides: dict = {}
    if byok_resolver is None:
        return overrides
    from app.domains.routing.providers.registry import build_adapter

    for candidate in route.order:
        secret = byok_resolver(candidate.provider_key)
        if secret:
            override = build_adapter(candidate.provider_key, secret)
            if override is not None:
                overrides[candidate.provider_key] = override
    return overrides

_adapters_registered = False


def ensure_adapters_registered() -> list[str]:
    """Register credential-backed provider adapters once, behind the launch flag.

    A no-op unless generation is enabled for the current launch phase. Safe to
    call repeatedly (registration is keyed + guarded). Returns the provider keys
    registered on this call (empty when gated off or already done).
    """
    global _adapters_registered
    if _adapters_registered:
        return []

    # Registration only makes outbound protocols available; a model still must be
    # promoted live in the catalog before a client can select it. We register
    # whenever credentials exist so shadow-mode evaluation can run.
    from app.domains.routing.providers.registry import register_available_adapters

    keys = register_available_adapters()
    _adapters_registered = True
    if keys:
        logger.info(f"generation runtime: provider adapters ready: {keys}")
    return keys


def execute_and_record(
    session: Session,
    *,
    capability: str,
    model_id: str,
    request: dict,
    job_id: str,
    account_id: str | None = None,
    policy: RoutePolicy | None = None,
    estimated_quantity: int | None = None,
    correlation_id: str = "",
    stage: str = "",
    provider_registry: Any = None,
    sleep_fn: Any = None,
    byok_resolver: Any = None,
) -> ExecutionResult:
    """Resolve + run a route for a job stage and record its measured cost.

    Persists a ``usage_records`` row (via the engine) and merges the measured
    ``actual_micros`` into the job's wallet marker so the job's terminal
    settlement charges the actual amount and releases the unused reservation.
    ``byok_resolver(provider_key) -> secret|None`` (optional) binds a candidate's
    provider to the customer's own key (BYOK) for that run. Raises
    ``RoutingError`` when no route is admissible or every candidate fails.
    """
    routing = RoutingService(session, provider_registry=provider_registry)
    route = routing.resolve_route(
        capability=capability,
        model_id=model_id,
        policy=policy,
        estimated_quantity=estimated_quantity,
    )

    # BYOK: for each candidate provider with a stored customer key, build a
    # per-request adapter bound to that key. Audit happens inside the resolver.
    adapter_overrides = _byok_overrides(route, byok_resolver)

    # Record each provider attempt's outcome for health-weighted routing.
    from app.domains.catalog.health import ProviderHealthService

    health = ProviderHealthService(session)

    def _record_health(provider_key, ok, latency_ms, capability=""):
        try:
            health.record(provider_key, ok=ok, latency_ms=latency_ms, capability=capability)
        except Exception:  # noqa: BLE001 - health telemetry must never break a job
            pass

    result = routing.execute(
        route,
        request,
        correlation_id=correlation_id,
        stage=stage,
        job_id=job_id,
        account_id=account_id,
        sleep_fn=sleep_fn,
        adapter_overrides=adapter_overrides,
        health_recorder=_record_health,
    )

    # Record the measured cost onto the wallet marker (no-op for classic jobs).
    from app.domains.reels.wallet_bridge import record_actual_micros

    record_actual_micros(session, job_id=job_id, actual_micros=result.cost_micros)
    return result


def run_generation_job(
    job_id: str,
    *,
    capability: str,
    model_id: str,
    request: dict,
    correlation_id: str = "",
    provider_registry: Any = None,
    sleep_fn: Any = None,
    user_id: str = "",
    use_byok: bool = False,
) -> dict:
    """Open a session, run one provider generation, and return a compact result.

    The Celery generation task's thin entry point. Registers credential-backed
    adapters first (unless a registry is injected for tests), runs the routing
    engine + records the measured cost, and returns a JSON-safe summary. When
    ``use_byok`` and a ``user_id`` are given, the customer's own stored provider
    key funds the outbound call (per-use audited). A ``RoutingError`` propagates
    so Celery's retry/terminal machinery applies.
    """
    from app.models.db.base import get_session

    if provider_registry is None:
        ensure_adapters_registered()
    with get_session() as session:
        byok_resolver = _byok_resolver_for(session, user_id, use_byok)
        result = execute_and_record(
            session,
            capability=capability,
            model_id=model_id,
            request=request,
            job_id=job_id,
            correlation_id=correlation_id,
            stage=capability,
            provider_registry=provider_registry,
            sleep_fn=sleep_fn,
            byok_resolver=byok_resolver,
        )
        return {
            "job_id": job_id,
            "provider_key": result.provider_key,
            "model_id": result.model_id,
            "result_ref": result.result_ref,
            "cost_micros": int(result.cost_micros),
            "usage_record_id": result.usage_record_id,
        }


def run_marketplace_pipeline(
    session,
    *,
    job_id: str,
    stages: dict,
    requests: dict | None = None,
    user_id: str = "",
    use_byok: bool = False,
    provider_registry: Any = None,
    sleep_fn: Any = None,
) -> dict:
    """Run every marketplace stage of a job's profile through the routing engine.

    ``stages`` maps ``capability -> model_id`` (a resolved generation profile).
    Each stage runs the routing engine (submit -> poll), pricing usage from OUR
    price version and persisting a ``usage_records`` row; per-stage costs are
    ACCUMULATED and the total is stamped once onto the job's wallet marker so the
    job's terminal settlement charges the aggregate actual (releasing the unused
    reservation). BYOK is honored per stage. Raises ``RoutingError`` if any stage
    has no admissible route or every candidate fails.
    """
    routing = RoutingService(session, provider_registry=provider_registry)
    byok_resolver = _byok_resolver_for(session, user_id, use_byok)
    reqs = requests or {}

    total_micros = 0
    stage_results: dict = {}
    for capability, model_id in stages.items():
        route = routing.resolve_route(capability=capability, model_id=model_id)
        overrides = _byok_overrides(route, byok_resolver)
        result = routing.execute(
            route,
            reqs.get(capability, {}),
            correlation_id=job_id,
            stage=capability,
            job_id=job_id,
            adapter_overrides=overrides,
            sleep_fn=sleep_fn,
        )
        total_micros += int(result.cost_micros)
        stage_results[capability] = {
            "model_id": result.model_id,
            "provider_key": result.provider_key,
            "cost_micros": int(result.cost_micros),
            "result_ref": result.result_ref,
            "usage_record_id": result.usage_record_id,
        }

    # Stamp the AGGREGATE actual cost once (not per stage) for terminal settlement.
    from app.domains.reels.wallet_bridge import record_actual_micros

    record_actual_micros(session, job_id=job_id, actual_micros=total_micros)
    return {
        "job_id": job_id,
        "total_cost_micros": total_micros,
        "stages": stage_results,
    }


def run_marketplace_reel_job(
    job_id: str,
    *,
    stages: dict,
    requests: dict | None = None,
    user_id: str = "",
    use_byok: bool = False,
) -> dict:
    """Celery entry point: open a session and run the full marketplace pipeline."""
    from app.models.db.base import get_session

    ensure_adapters_registered()
    with get_session() as session:
        return run_marketplace_pipeline(
            session,
            job_id=job_id,
            stages=stages,
            requests=requests,
            user_id=user_id,
            use_byok=use_byok,
        )
