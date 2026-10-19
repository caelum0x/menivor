"""Best-effort ``httpx`` client to the live **Rago** usage-metering API.

Rago is the Lago-compatible metering rail (railyard ``apps/rago``). This client
mirrors :mod:`app.domains.wallet.mint_client`'s shape — an injectable
``httpx.Client`` (or ``transport`` for tests), a config gate, and a
process-cached factory that never opens a socket at import time — but it serves a
different purpose. Mint is the *money* rail (a job holds/captures/releases real
microdollars); Rago is an **additive metering shadow**: when a job settles, its
measured media/LLM spend is reported to Rago as a usage event
(``POST /api/v1/events``) so the same spend is visible for Rago-side rating and
analytics even though the money itself lives on Mint (or the local ledger).

Because Rago is a shadow and not the source of truth, metering is *best-effort*
and *env-gated*:

* When ``RAGO_URL``/``RAGO_API_KEY`` are unset, :func:`rago_enabled` is ``False``
  and :func:`meter_job_settlement` is a logged no-op — nothing is metered.
* Any failure (unconfigured, transport error, non-2xx, a bad subscription) is
  caught and logged by :func:`meter_job_settlement`; it never raises, so a
  metering hiccup can never fail a settled job.

The event carries ``transaction_id = "{job_id}:settle"`` so a job reported twice
is de-duplicated by Rago's ``(subscription, transaction_id)`` index and never
double-metered.
"""

from __future__ import annotations

from decimal import Decimal
import threading
import time
from typing import Any

import httpx
from loguru import logger

# Default per-request timeout (seconds) when the caller does not override it.
_DEFAULT_TIMEOUT = 10.0

# Default ``billable_metric.code`` a settled job is metered against. Rago must be
# provisioned with a matching metric; overridable via ``RAGO_METRIC_CODE``.
DEFAULT_METRIC_CODE = "reel_ai_credits"

# ReelForge micros are microdollars; Rago prices in cents. 1 cent = 10_000 micros.
MICROS_PER_CENT = 10_000


class RagoClientError(Exception):
    """A Rago metering failure (HTTP status + safe message).

    Raised only by the low-level :class:`RagoClient`; the best-effort
    :func:`meter_job_settlement` wrapper catches it so callers never see it.
    """

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class RagoClient:
    """A thin, injectable HTTP client over Rago's ``/api/v1/events`` ingest."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        if client is not None:
            # Tests inject a MockTransport-backed client; no socket is opened.
            self._client = client
        else:
            # Real runtime: a live socket to rago (satisfies the no-stub rule).
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=self._auth_headers(),
                timeout=timeout,
                transport=transport,
            )

    # ------------------------------------------------------------------ #
    # Envelope helpers
    # ------------------------------------------------------------------ #
    def _auth_headers(self) -> dict[str, str]:
        # Rago authenticates every ``/api/v1`` route with a Bearer API key. Send
        # it on each request so an injected bare client is authenticated too (and
        # the header is observable in tests).
        return {"authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        try:
            response = self._client.post(path, json=body, headers=self._auth_headers())
        except httpx.RequestError as exc:
            raise RagoClientError(502, f"rago unreachable: {exc}") from exc
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        """Return the decoded body on a 2xx; else raise a mapped error."""
        if 200 <= response.status_code < 300:
            try:
                return response.json()
            except ValueError:
                return None
        message = f"rago error (status {response.status_code})"
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("error") or payload.get("message")
            if isinstance(detail, str) and detail:
                message = detail
        raise RagoClientError(response.status_code, message)

    # ------------------------------------------------------------------ #
    # Usage events
    # ------------------------------------------------------------------ #
    def record_event(
        self,
        *,
        code: str,
        transaction_id: str,
        external_subscription_id: str,
        properties: dict[str, Any] | None = None,
        timestamp: float | None = None,
        precise_total_amount_cents: str | None = None,
    ) -> Any:
        """Ingest one usage event via ``POST /api/v1/events``.

        Rago wraps the event in an ``{"event": {...}}`` envelope. ``code`` selects
        the billable metric; ``transaction_id`` is the idempotency key;
        ``external_subscription_id`` is the metered subscription. Numeric usage
        goes in ``properties`` as bare JSON numbers.
        """
        event: dict[str, Any] = {
            "code": code,
            "transaction_id": transaction_id,
            "external_subscription_id": external_subscription_id,
            "properties": properties or {},
        }
        if timestamp is not None:
            event["timestamp"] = timestamp
        if precise_total_amount_cents is not None:
            event["precise_total_amount_cents"] = precise_total_amount_cents
        return self._post("/api/v1/events", {"event": event})


# --------------------------------------------------------------------------- #
# Config gate + process-cached factory
# --------------------------------------------------------------------------- #
_CACHE_LOCK = threading.Lock()
_cached_client: RagoClient | None = None


def rago_enabled() -> bool:
    """True when a Rago URL + api_key are configured (else metering is off)."""
    from app.config import config

    return bool(config.rago.get("url") and config.rago.get("api_key"))


def rago_client_from_config() -> RagoClient | None:
    """Return the process-cached :class:`RagoClient`, or ``None`` when disabled.

    Requires both ``RAGO_URL`` and ``RAGO_API_KEY``; when either is missing
    metering is disabled and callers simply skip it.
    """
    global _cached_client
    from app.config import config

    url = config.rago.get("url")
    api_key = config.rago.get("api_key")
    if not url or not api_key:
        return None
    with _CACHE_LOCK:
        if _cached_client is None:
            try:
                timeout = float(config.rago.get("timeout_seconds", _DEFAULT_TIMEOUT))
            except (TypeError, ValueError):
                timeout = _DEFAULT_TIMEOUT
            _cached_client = RagoClient(str(url), str(api_key), timeout=timeout)
        return _cached_client


def reset_rago_client_cache() -> None:
    """Drop the process-cached client (config changed / tests)."""
    global _cached_client
    with _CACHE_LOCK:
        _cached_client = None


def meter_job_settlement(
    *,
    job_id: str,
    actual_micros: int,
    owner_key: str,
    settlement_rail: str = "local",
    external_subscription_id: str | None = None,
    timestamp: float | None = None,
) -> bool:
    """Best-effort: report a settled job's media/LLM spend to Rago.

    Additive + env-gated: returns ``False`` (a logged no-op) when Rago is not
    configured, and swallows every error so a metering failure can never fail a
    settled job — the money rail (Mint hold/capture or the local ledger) remains
    the source of truth. Returns ``True`` only when an event was actually sent.

    ``actual_micros`` is the measured spend (microdollars); ``owner_key`` is the
    wallet owner (workspace id for a shared pool, else the user id) used as the
    metered subscription unless an explicit ``external_subscription_id`` (or the
    ``RAGO_EXTERNAL_SUBSCRIPTION_ID`` config) is provided.
    """
    try:
        client = rago_client_from_config()
        if client is None:
            logger.debug(f"rago metering disabled; skipping job {job_id}")
            return False

        from app.config import config

        code = str(config.rago.get("metric_code") or DEFAULT_METRIC_CODE)
        subscription = (
            external_subscription_id
            or str(config.rago.get("external_subscription_id") or "")
            or str(owner_key or "")
        ).strip()
        if not subscription:
            logger.debug(
                f"rago metering skipped for job {job_id}: no subscription id"
            )
            return False

        micros = max(0, int(actual_micros))
        cents = Decimal(micros) / Decimal(MICROS_PER_CENT)
        client.record_event(
            code=code,
            transaction_id=f"{job_id}:settle",
            external_subscription_id=subscription,
            properties={
                "credits": micros,
                "job_id": str(job_id),
                "settlement_rail": str(settlement_rail),
            },
            timestamp=timestamp if timestamp is not None else time.time(),
            precise_total_amount_cents=format(cents, "f"),
        )
        logger.info(
            f"metered job {job_id} spend to rago "
            f"({micros} micros, rail={settlement_rail})"
        )
        return True
    except Exception as exc:  # noqa: BLE001 - metering must never fail the job
        logger.warning(f"rago metering failed for job {job_id} (ignored): {exc}")
        return False
