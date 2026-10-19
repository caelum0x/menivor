"""Additive wallet integration for reel jobs (generation_profile_id path).

This is the **additive-shadow** bridge (PROVIDER_MARKETPLACE_PLAN.md §4.1): a
job created with a signed generation quote reserves its max cost from the USD
wallet before dispatch, settles the actual cost on success, and releases the
hold on failure. Jobs created the classic way (no quote) keep using the fixed
``CreditLedger`` and are untouched by any code here.

The reservation is recorded inside ``Job.params['_wallet']`` (JSON, no
migration) so the worker's terminal hooks can settle/release without a new
column. Every helper is import-safe and best-effort at the edges: a wallet
failure at create surfaces as a clean HTTP error; a settle/release failure in
the worker is logged, never raised (mirroring the existing best-effort hooks).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger

# Namespaced marker key inside Job.params. Underscore-prefixed like the existing
# ``_correlation_id`` so it never collides with a real ReelForge param field.
WALLET_MARKER_KEY = "_wallet"


class WalletBridgeError(Exception):
    """A caller-facing wallet-bridge failure (HTTP status + safe message)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class WalletIntent:
    """A validated intent to fund a job from the wallet, parsed off the request."""

    profile: str
    quote: dict
    max_cost_micros: int
    workspace_id: str = ""


def _parse_expiry(value: Any) -> datetime | None:
    """Parse an ISO ``expires_at`` into an aware UTC datetime, or None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def extract_wallet_intent(body: Any) -> WalletIntent | None:
    """Return a :class:`WalletIntent` when the request opts into wallet funding.

    Opt-in signal: a ``quote`` object (the server-signed snapshot from
    ``POST /catalog/quotes/generation``) AND a ``generation_profile_id``. Absent
    either, the job uses the classic credit path and this returns ``None``.
    Never raises — a malformed shape simply resolves to "not a wallet job".
    """
    getter = (
        body.get if isinstance(body, dict) else lambda k, d=None: getattr(body, k, d)
    )
    profile = getter("generation_profile_id", None) or getter("profile", None)
    quote = getter("quote", None)
    if not profile or not isinstance(quote, dict):
        return None
    try:
        max_cost = int(quote.get("max_cost_micros", 0) or 0)
    except (TypeError, ValueError):
        return None
    if max_cost <= 0:
        return None
    workspace_id = getter("workspace_id", "") or ""
    return WalletIntent(
        profile=str(profile),
        quote=quote,
        max_cost_micros=max_cost,
        workspace_id=str(workspace_id),
    )


def validate_intent(session: Any, intent: WalletIntent, request_id: str) -> None:
    """Verify the quote signature + expiry before any reservation.

    Raises :class:`WalletBridgeError` (422) for a tampered or expired quote so a
    client can never submit an arbitrary price (PROVIDER_MARKETPLACE_PLAN.md §8).
    """
    from app.domains.catalog.service import CatalogService

    if not CatalogService(session).verify_quote_snapshot(intent.quote):
        raise WalletBridgeError(422, "quote signature is invalid")
    expires = _parse_expiry(intent.quote.get("expires_at"))
    if expires is not None and expires <= datetime.now(timezone.utc):
        raise WalletBridgeError(422, "quote has expired; request a fresh quote")


def reserve_for_job(
    session: Any,
    *,
    user_id: str,
    intent: WalletIntent,
    job_id: str,
    request_id: str,
) -> dict:
    """Reserve the quoted max cost on the wallet and return the params marker.

    Maps an insufficient balance to a 402 via :class:`WalletBridgeError`. The
    returned dict is merged into ``Job.params`` so the worker can settle/release.
    """
    from app.domains.wallet.service import WalletError, WalletService

    workspace_id = (intent.workspace_id or "").strip() or None

    # Enforce team spend role + budget BEFORE holding funds (no-op when unset).
    # A workspace job requires the caller's role to satisfy the pool's spend
    # policy and its budget; a personal job checks the user's own budget.
    try:
        from app.domains.spend.roles import SPEND
        from app.domains.spend.service import SpendError, SpendPolicyService

        spend = SpendPolicyService(session)
        if workspace_id:
            spend.assert_can(SPEND, workspace_id, user_id)
            spend.ensure_within_budget_workspace(workspace_id, intent.max_cost_micros)
        else:
            spend.ensure_within_budget(user_id, intent.max_cost_micros)
    except SpendError as exc:
        raise WalletBridgeError(exc.status_code, exc.message) from exc
    except WalletBridgeError:
        raise
    except Exception as exc:  # noqa: BLE001 - spend layer optional; never block on its absence
        logger.debug(f"spend-role/budget check skipped for job {job_id}: {exc}")

    # Mint-settlement rail: when the launch stage routes THIS owner to Mint, HOLD
    # the quoted max on the live mint-server instead of the local ledger (no
    # double charge). The stage machinery (local -> canary -> on) decides per
    # owner, so a rollout can be flipped forward/back purely via config. The
    # marker is stamped with mint_hold_id so settle/release always route to Mint
    # even if the stage later changes. A WalletBridgeError (402/403/…) propagates
    # so the create endpoint returns a clean status and the whole DB txn rolls back.
    from app.domains.wallet.mint_client import mint_client_from_config
    from app.domains.wallet.mint_stage import should_use_mint

    owner_key = workspace_id or user_id
    if should_use_mint(owner_key):
        client = mint_client_from_config()
        if client is not None:
            from app.domains.wallet.mint_accounts import resolve_mint_account

            mint_account = resolve_mint_account(
                session, user_id, workspace_id, client=client
            )
            quote_id = str(intent.quote.get("quote_id", ""))
            receipt = client.create_hold(
                from_account=mint_account,
                amount_micros=intent.max_cost_micros,
                idem_key=job_id,
                ref=quote_id or None,
            )
            return {
                WALLET_MARKER_KEY: {
                    "reserved_micros": intent.max_cost_micros,
                    "profile": intent.profile,
                    "quote_id": quote_id,
                    "correlation_id": request_id,
                    "workspace_id": workspace_id or "",
                    "mint_hold_id": str(receipt["hold_id"]),
                    "mint_account": mint_account,
                }
            }

    try:
        WalletService(session).reserve(
            user_id,
            amount_micros=intent.max_cost_micros,
            job_id=job_id,
            correlation_id=request_id,
            workspace_id=workspace_id,
        )
    except WalletError as exc:
        raise WalletBridgeError(exc.status_code, exc.message) from exc
    return {
        WALLET_MARKER_KEY: {
            "reserved_micros": intent.max_cost_micros,
            "profile": intent.profile,
            "quote_id": str(intent.quote.get("quote_id", "")),
            "correlation_id": request_id,
            "workspace_id": workspace_id or "",
        }
    }


def read_marker(params: Any) -> dict | None:
    """Return the wallet marker from a job's stored params, or None."""
    if not isinstance(params, dict):
        return None
    marker = params.get(WALLET_MARKER_KEY)
    return marker if isinstance(marker, dict) else None


def _mint_capture(marker: dict, *, job_id: str, reserved: int, actual: int) -> bool:
    """CAPTURE the actual on Mint. Returns True (ADR-0002 success-only billing).

    A single ``capture`` settles the whole hold: the real mint-server credits the
    captured amount to the treasury AND atomically returns the uncaptured
    remainder (``reserved - actual``) to the payer's available balance, closing
    the hold. There is therefore no separate ``release`` to issue — doing so would
    hit an already-closed hold (``404 HoldNotFound``). Verified end-to-end against
    the live mint-server (``test_mint_settlement_integration``).

    Idempotent per job: capture=``{job_id}:capture`` so a duplicate terminal hook
    replays the same receipt instead of charging twice. A missing Mint client
    raises so the best-effort wrapper logs it. ``reserved`` is accepted for
    logging/symmetry; the capture amount is always the measured ``actual``.
    """
    from app.domains.wallet.mint_client import mint_client_from_config

    client = mint_client_from_config()
    if client is None:
        raise WalletBridgeError(502, "mint client is not configured for settle")
    hold_id = str(marker["mint_hold_id"])
    quote_id = str(marker.get("quote_id", "")) or None
    client.capture_hold(
        hold_id,
        amount_micros=actual,
        to=client.treasury_account,
        idem_key=f"{job_id}:capture",
        ref=quote_id,
    )
    return True


def _mint_release(marker: dict, *, job_id: str) -> bool:
    """RELEASE the full hold on Mint (failed job nets zero — ADR-0002)."""
    from app.domains.wallet.mint_client import mint_client_from_config

    client = mint_client_from_config()
    if client is None:
        raise WalletBridgeError(502, "mint client is not configured for release")
    hold_id = str(marker["mint_hold_id"])
    quote_id = str(marker.get("quote_id", "")) or None
    client.release_hold(hold_id, idem_key=f"{job_id}:release", ref=quote_id)
    return True


def _mark_mint_terminal(
    session: Any, *, job_id: str, status: str, receipt_kind: str
) -> None:
    """Persist that a Mint hold reached its terminal money outcome.

    The external Mint operation happens first. If this database write fails, the
    recovery sweep retries the same idempotency key and Mint replays the receipt;
    money can therefore never be marked settled before it actually is.
    """
    from app.models.db.models import Job

    job = session.get(Job, job_id)
    if job is None:
        return
    params = dict(job.params) if job.params else {}
    marker = read_marker(params)
    if not marker or not marker.get("mint_hold_id"):
        return
    updated = {
        **marker,
        "settlement_status": status,
        "settlement_receipt_kind": receipt_kind,
        "settled_at": datetime.now(timezone.utc).isoformat(),
    }
    job.params = {**params, WALLET_MARKER_KEY: updated}
    session.flush()


def _meter_settlement(
    marker: dict, *, user_id: str, job_id: str, actual_micros: int, rail: str
) -> None:
    """Best-effort: mirror a settled job's spend into Rago usage metering.

    Additive + env-gated (``RAGO_URL``/``RAGO_API_KEY``): a no-op when Rago is
    unset, and it swallows every error so metering can never fail a settlement.
    The money rail (Mint hold/capture or the local ledger) stays the source of
    truth; this only reports the measured media/LLM spend so it is visible in
    Rago too — for both Mint-held and local-ledger jobs. ``owner_key`` is the
    workspace id for a shared pool, else the settling user id.
    """
    try:
        from app.domains.wallet.rago_client import meter_job_settlement

        owner_key = str(marker.get("workspace_id", "") or "") or user_id
        meter_job_settlement(
            job_id=job_id,
            actual_micros=actual_micros,
            owner_key=owner_key,
            settlement_rail=rail,
        )
    except Exception as exc:  # noqa: BLE001 - metering is best-effort only
        logger.debug(f"rago metering skipped for job {job_id}: {exc}")
    try:
        # Railyard per-render usage event (no-op unless RAILYARD_RAGO_* is set;
        # sent off-thread so it never delays settlement).
        from app.integrations.railyard import meter_render

        meter_render(
            job_id=job_id,
            owner_key=str(marker.get("workspace_id", "") or "") or user_id,
            credits_micros=actual_micros,
            rail=rail,
        )
    except Exception as exc:  # noqa: BLE001 - metering is best-effort only
        logger.debug(f"railyard render metering skipped for job {job_id}: {exc}")


def settle_job(session: Any, *, user_id: str, job_id: str, params: Any) -> bool:
    """Settle a completed wallet job (fixed-price v1: actual == reserved).

    Returns True when a settlement was performed. Best-effort for the worker: a
    missing/zero marker is a no-op; a WalletError is surfaced to the caller which
    logs it (never crashes the pipeline).
    """
    marker = read_marker(params)
    if not marker:
        return False
    reserved = int(marker.get("reserved_micros", 0) or 0)
    if reserved <= 0:
        return False
    from app.domains.wallet.service import WalletService

    # Prefer a recorded MEASURED cost (written by the routing execution stage) so
    # the unused reservation is released; fall back to the fixed reserved amount
    # for providers without metered usage. Actual is always capped at reserved.
    raw_actual = marker.get("actual_micros")
    if raw_actual is not None:
        actual = max(0, min(int(raw_actual), reserved))
    else:
        actual = reserved
    if marker.get("mint_hold_id"):
        if marker.get("settlement_status") == "captured":
            return True
        settled = _mint_capture(marker, job_id=job_id, reserved=reserved, actual=actual)
        if settled:
            _mark_mint_terminal(
                session, job_id=job_id, status="captured", receipt_kind="capture"
            )
            _meter_settlement(
                marker,
                user_id=user_id,
                job_id=job_id,
                actual_micros=actual,
                rail="mint",
            )
        return settled
    WalletService(session).settle(
        user_id,
        reserved_micros=reserved,
        actual_micros=actual,
        job_id=job_id,
        correlation_id=str(marker.get("correlation_id", "")),
        workspace_id=(str(marker.get("workspace_id", "")) or None),
    )
    _meter_settlement(
        marker, user_id=user_id, job_id=job_id, actual_micros=actual, rail="local"
    )
    return True


def record_actual_micros(session: Any, *, job_id: str, actual_micros: int) -> bool:
    """Merge a measured usage cost into a wallet job's params marker.

    Called by the routing execution stage after a provider run completes so the
    job's terminal settlement charges the actual (not the reserved) amount.
    Returns True when the marker was updated (i.e. it is a wallet job).
    """
    from app.models.db.models import Job

    job = session.get(Job, job_id)
    if job is None:
        return False
    params = dict(job.params) if job.params else {}
    marker = read_marker(params)
    if not marker:
        return False
    new_marker = {**marker, "actual_micros": max(0, int(actual_micros))}
    job.params = {**params, WALLET_MARKER_KEY: new_marker}
    session.flush()
    return True


def settle_job_actual(
    session: Any, *, user_id: str, job_id: str, params: Any, actual_micros: int
) -> bool:
    """Settle a completed wallet job at the MEASURED cost, releasing the rest.

    ``actual_micros`` is the real usage cost (from the routing execution); it is
    capped at the reservation by the wallet service and the unused remainder is
    returned to available. A missing/zero marker is a no-op. Use this for metered
    providers; :func:`settle_job` remains the fixed-price path.
    """
    marker = read_marker(params)
    if not marker:
        return False
    reserved = int(marker.get("reserved_micros", 0) or 0)
    if reserved <= 0:
        return False
    actual = max(0, min(int(actual_micros), reserved))
    if marker.get("mint_hold_id"):
        if marker.get("settlement_status") == "captured":
            return True
        settled = _mint_capture(marker, job_id=job_id, reserved=reserved, actual=actual)
        if settled:
            _mark_mint_terminal(
                session, job_id=job_id, status="captured", receipt_kind="capture"
            )
            _meter_settlement(
                marker,
                user_id=user_id,
                job_id=job_id,
                actual_micros=actual,
                rail="mint",
            )
        return settled
    from app.domains.wallet.service import WalletService

    WalletService(session).settle(
        user_id,
        reserved_micros=reserved,
        actual_micros=actual,
        job_id=job_id,
        correlation_id=str(marker.get("correlation_id", "")),
        workspace_id=(str(marker.get("workspace_id", "")) or None),
    )
    _meter_settlement(
        marker, user_id=user_id, job_id=job_id, actual_micros=actual, rail="local"
    )
    return True


def release_job(session: Any, *, user_id: str, job_id: str, params: Any) -> bool:
    """Release a failed wallet job's reservation. Returns True when released."""
    marker = read_marker(params)
    if not marker:
        return False
    reserved = int(marker.get("reserved_micros", 0) or 0)
    if reserved <= 0:
        return False
    if marker.get("mint_hold_id"):
        if marker.get("settlement_status") == "released":
            return True
        released = _mint_release(marker, job_id=job_id)
        if released:
            _mark_mint_terminal(
                session, job_id=job_id, status="released", receipt_kind="release"
            )
        return released
    from app.domains.wallet.service import WalletService

    WalletService(session).release(
        user_id,
        reserved_micros=reserved,
        job_id=job_id,
        correlation_id=str(marker.get("correlation_id", "")),
        workspace_id=(str(marker.get("workspace_id", "")) or None),
    )
    return True


def safe_settle_job(user_id: str, job_id: str, params: Any) -> None:
    """Best-effort settlement in its own committed transaction (worker hook)."""
    from app.models.db.base import get_session

    try:
        with get_session() as session:
            settle_job(session, user_id=user_id, job_id=job_id, params=params)
    except Exception as exc:  # noqa: BLE001 - never break the pipeline on settle
        logger.error(f"wallet settle failed for job {job_id}: {exc}")


def safe_release_job(user_id: str, job_id: str, params: Any) -> None:
    """Best-effort reservation release in its own transaction (worker/reconcile)."""
    from app.models.db.base import get_session

    try:
        with get_session() as session:
            release_job(session, user_id=user_id, job_id=job_id, params=params)
    except Exception as exc:  # noqa: BLE001 - never break the pipeline on release
        logger.error(f"wallet release failed for job {job_id}: {exc}")


def _load_job_wallet_context(session: Any, job_id: str) -> tuple[str, dict] | None:
    """Load a job's (user_id, params) when it is a wallet-funded job, else None.

    The worker's task ``ctx`` does not carry the persisted job params (the
    ``_wallet`` marker lives on the DB row), so the terminal hooks load it here.
    """
    from app.models.db.models import Job

    job = session.get(Job, job_id)
    if job is None:
        return None
    params = dict(job.params) if job.params else {}
    if read_marker(params) is None:
        return None
    return str(job.user_id or ""), params


def safe_settle_job_by_id(job_id: str) -> None:
    """Best-effort settle for a completed job, loading its marker from the DB.

    A no-op for classic (non-wallet) jobs. Called from the worker's terminal
    completion hook; never raises so it can't break the pipeline.
    """
    from app.models.db.base import get_session

    try:
        with get_session() as session:
            ctx = _load_job_wallet_context(session, job_id)
            if ctx is None:
                return
            user_id, params = ctx
            settle_job(session, user_id=user_id, job_id=job_id, params=params)
    except Exception as exc:  # noqa: BLE001 - never break the pipeline on settle
        logger.error(f"wallet settle-by-id failed for job {job_id}: {exc}")


def safe_release_job_by_id(job_id: str) -> None:
    """Best-effort release for a terminally failed job (marker loaded from DB)."""
    from app.models.db.base import get_session

    try:
        with get_session() as session:
            ctx = _load_job_wallet_context(session, job_id)
            if ctx is None:
                return
            user_id, params = ctx
            release_job(session, user_id=user_id, job_id=job_id, params=params)
    except Exception as exc:  # noqa: BLE001 - never break the pipeline on release
        logger.error(f"wallet release-by-id failed for job {job_id}: {exc}")


def reconcile_terminal_mint_holds(session: Any, *, limit: int = 100) -> dict[str, int]:
    """Recover terminal jobs whose persisted Mint hold was not settled.

    A worker can die after it marks a job complete/failed but before the normal
    terminal hook reaches Mint. This bounded query finds only Mint-backed,
    terminal jobs without a persisted settlement outcome and replays the same
    capture/release idempotency key. Each job is isolated so one transient Mint
    outage cannot prevent the remaining recoveries in the batch.
    """
    from sqlalchemy import select

    from app.models import const
    from app.models.db.models import Job

    bounded = max(1, min(int(limit), 500))
    stmt = (
        select(Job)
        .where(
            Job.state.in_((const.TASK_STATE_COMPLETE, const.TASK_STATE_FAILED)),
            Job.params[WALLET_MARKER_KEY]["mint_hold_id"].as_string().is_not(None),
            Job.params[WALLET_MARKER_KEY]["settlement_status"].as_string().is_(None),
        )
        .order_by(Job.updated_at.asc(), Job.id.asc())
        .limit(bounded)
    )
    jobs = list(session.execute(stmt).scalars().all())
    summary = {"scanned": len(jobs), "captured": 0, "released": 0, "errored": 0}
    for job in jobs:
        params = dict(job.params) if job.params else {}
        try:
            if job.state == const.TASK_STATE_COMPLETE:
                if settle_job(
                    session,
                    user_id=str(job.user_id or ""),
                    job_id=str(job.id),
                    params=params,
                ):
                    summary["captured"] += 1
            elif release_job(
                session,
                user_id=str(job.user_id or ""),
                job_id=str(job.id),
                params=params,
            ):
                summary["released"] += 1
        except Exception as exc:  # noqa: BLE001 - isolate recovery per job
            summary["errored"] += 1
            logger.error(f"wallet Mint reconciliation failed for job {job.id}: {exc}")
    return summary


def run_mint_settlement_reconciliation(*, limit: int = 100) -> dict[str, int]:
    """Open a committed session and run one bounded Mint recovery pass."""
    from app.models.db.base import get_session

    with get_session() as session:
        return reconcile_terminal_mint_holds(session, limit=limit)
