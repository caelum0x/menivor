"""Sentry error/performance monitoring wiring (CTO locked decision, DoD #5).

Fully optional and NO-OP by default: when ``[sentry].dsn`` is empty (the ship
default), :func:`init_sentry` logs that Sentry is disabled and returns without
importing anything, so no key is required to run. When a DSN *is* configured,
``sentry_sdk`` is lazy-imported and initialised with whichever of the FastAPI /
Celery integrations are installed, tagged with the calling ``component``.

The ``import sentry_sdk`` is guarded so this module always ``py_compile``s and
imports cleanly even when the optional dependency is absent.
"""

from __future__ import annotations

import threading

from loguru import logger

from app.config import config

# Guard against double-initialisation. FastAPI startup and the Celery worker
# bootstrap can each call ``init_sentry`` once; a re-entrant call (e.g. a worker
# restart in the same process) must not register the integrations twice.
_init_lock = threading.Lock()
_initialised_components: set[str] = set()


def _coerce_sample_rate(raw: object) -> float:
    """Best-effort parse of ``traces_sample_rate`` into a clamped float.

    Config values may arrive as strings (env overrides) or numbers. Invalid
    input falls back to ``0.0`` (errors only) rather than raising, so a typo in
    config never takes down process startup.
    """
    try:
        rate = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.warning(
            f"invalid sentry traces_sample_rate {raw!r}; defaulting to 0.0"
        )
        return 0.0
    return min(1.0, max(0.0, rate))


def _build_integrations() -> list:
    """Return the Sentry integrations available in this environment.

    Each integration import is guarded independently: the API process may not
    have Celery loaded and a worker may not import FastAPI, and neither should
    fail initialisation. Missing integrations are simply skipped.
    """
    integrations: list = []

    try:
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        integrations.append(FastApiIntegration())
    except Exception as exc:  # pragma: no cover - depends on optional extras
        logger.debug(f"sentry FastAPI integration unavailable: {exc}")

    try:
        from sentry_sdk.integrations.celery import CeleryIntegration

        integrations.append(CeleryIntegration())
    except Exception as exc:  # pragma: no cover - depends on optional extras
        logger.debug(f"sentry Celery integration unavailable: {exc}")

    return integrations


def init_sentry(component: str) -> bool:
    """Initialise Sentry for ``component`` (``"api"`` / ``"worker"``).

    Returns ``True`` when ``sentry_sdk.init`` was invoked, ``False`` when Sentry
    is disabled (no DSN), the SDK is not installed, or this component was
    already initialised. Never raises: monitoring must never break startup.

    Args:
        component: Short tag identifying the caller (e.g. ``"api"``,
            ``"worker"``) recorded on every event via the ``component`` tag.
    """
    dsn = str(config.sentry.get("dsn", "") or "").strip()
    if not dsn:
        logger.info(f"sentry disabled (no dsn configured) for '{component}'")
        return False

    with _init_lock:
        if component in _initialised_components:
            logger.debug(f"sentry already initialised for '{component}'")
            return False

        try:
            import sentry_sdk
        except Exception as exc:
            logger.warning(
                f"sentry_sdk not installed; monitoring disabled for "
                f"'{component}': {exc}"
            )
            return False

        try:
            environment = str(
                config.sentry.get("environment", "") or ""
            ).strip() or None
            traces_sample_rate = _coerce_sample_rate(
                config.sentry.get("traces_sample_rate", 0.0)
            )
            sentry_sdk.init(
                dsn=dsn,
                environment=environment,
                traces_sample_rate=traces_sample_rate,
                integrations=_build_integrations(),
            )
            try:
                sentry_sdk.set_tag("component", component)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug(f"failed to set sentry component tag: {exc}")

            _initialised_components.add(component)
            logger.info(
                f"sentry initialised for '{component}' "
                f"(environment={environment or 'unset'}, "
                f"traces_sample_rate={traces_sample_rate})"
            )
            return True
        except Exception as exc:
            logger.warning(f"failed to initialise sentry for '{component}': {exc}")
            return False


def capture_exception(
    exc: BaseException,
    *,
    stage: str = "",
    context: dict | None = None,
    client: object | None = None,
) -> bool:
    """Report an exception to Sentry with structured context (best-effort).

    Used by the pipeline/render failure handlers to surface a stage error with
    tags (``stage``) + extra context (job id, backend, cost) so an operator can
    triage from Sentry. NO-OP + returns ``False`` when ``sentry_sdk`` is absent or
    uninitialised; NEVER raises into the caller's error path. ``client`` is an
    injectable seam so the capture path is unit-testable without a live DSN.
    """
    sdk = client
    if sdk is None:
        try:
            import sentry_sdk as sdk  # type: ignore[no-redef]
        except Exception:
            return False
    try:
        scope_ctx = dict(context or {})
        set_scope = getattr(sdk, "push_scope", None)
        if callable(set_scope):
            with sdk.push_scope() as scope:  # type: ignore[attr-defined]
                if stage:
                    scope.set_tag("stage", stage)
                for key, value in scope_ctx.items():
                    scope.set_extra(str(key), value)
                sdk.capture_exception(exc)
        else:  # a minimal client (e.g. a test fake) without scopes
            sdk.capture_exception(exc)
        return True
    except Exception as report_exc:  # pragma: no cover - reporting must never raise
        logger.debug(f"sentry capture_exception failed: {report_exc}")
        return False
