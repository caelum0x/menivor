"""Unified media gateway — OpenRouter-style ``/images`` + ``/videos``.

One key + one wallet balance → any image/video model. Resolves the request's
``model`` in ``media_catalog``, routes to the real upstream adapter, meters the
wallet (reserve on create, settle actual on completion, refund on failure), and —
for video — persists a :class:`MediaJob` the client polls. Synchronous images
also persist a terminal row so every modality appears in account history.

Every catalog video provider has a real backend: **Kling via fal.ai**
(``KlingFalAdapter``), **Runway Gen-4** (``RunwayAdapter``), **Veo via Google's
Generative Language API** (``VeoAdapter``), **Luma Dream Machine** (``LumaAdapter``),
**MiniMax/Hailuo** (``MinimaxAdapter``), **Wan 2.2 via Replicate** (``WanAdapter``),
plus a real fal.ai sync image call for ``fal-image``. A provider whose API key is
unset returns a clear 503 (and the reservation is refunded) rather than faking a
result — honest degradation. A provider not present in the catalog dispatch raises
501.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from loguru import logger

from reelforge_provider_adapter.execution import (
    ProviderExecutionException,
    ProviderHandleV1,
    ProviderRequestV1,
    ProviderResultV1,
)

from app.domains.gateway.media_catalog import AUDIO, IMAGE, VIDEO, MediaModel, get_model, get_row, retired
from app.domains.gateway.provider_execution import MediaProviderExecutor
from app.domains.gateway.video_brief import (
    ROLE_FIRST_FRAME,
    Reference,
    ordered_references,
    public_https_url,
)
from app.domains.gateway.prism_client import PrismClientError, prism_client_from_config
from app.domains.routing.providers.kling_fal import KlingError
from app.models.db.media_jobs import MediaJob


class GatewayError(Exception):
    """A gateway request failed (unknown model, unsupported provider, upstream error)."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.status_code = status_code
        super().__init__(message)


# --------------------------------------------------------------------------- #
# Observability — best-effort emitters (mirror the render executor). The
# success-only-billing SLO correlates ``wallet_debit_micros{reason=gateway}``
# with ``media_gateway_jobs{status=completed}``; a failed job emits the job
# counter but NEVER a debit.
# --------------------------------------------------------------------------- #
def _metric_job(modality: str, provider: str, status: str) -> None:
    try:
        from app.telemetry.metrics import record_media_gateway_job

        record_media_gateway_job(modality, provider, status)
    except Exception:  # pragma: no cover - metrics are best-effort
        pass


def _metric_debit(micros: int) -> None:
    try:
        from app.telemetry.metrics import record_wallet_debit

        record_wallet_debit("gateway", micros)
    except Exception:  # pragma: no cover
        pass


# --------------------------------------------------------------------------- #
# Wallet metering (via the real WalletService)
# --------------------------------------------------------------------------- #
def _reserve(session: Any, user_id: str, micros: int, job_id: str) -> None:
    from app.domains.wallet.service import WalletError, WalletService

    try:
        WalletService(session).reserve(
            user_id,
            amount_micros=micros,
            job_id=job_id,
            correlation_id=f"gateway_{job_id}",
        )
    except WalletError as exc:
        raise GatewayError(exc.message, status_code=exc.status_code) from exc


def _settle(session: Any, user_id: str, held: int, actual: int, job_id: str) -> None:
    from app.domains.wallet.service import WalletService

    WalletService(session).settle(
        user_id,
        reserved_micros=held,
        actual_micros=min(actual, held),
        job_id=job_id,
        correlation_id=f"gateway_{job_id}",
    )


def _release(session: Any, user_id: str, held: int, job_id: str) -> None:
    from app.domains.wallet.service import WalletService

    WalletService(session).release(
        user_id, reserved_micros=held, job_id=job_id, correlation_id=f"gateway_{job_id}"
    )


def _correlation_id(row: MediaJob) -> str:
    """Assign/read the portable business request id after SQLAlchemy creates id."""
    if not row.correlation_id:
        if not row.id:
            raise GatewayError("media job has no durable id", status_code=500)
        row.correlation_id = f"gateway_{row.id}"
    return row.correlation_id


def _prepare_identity(
    session: Any,
    *,
    user_id: str,
    passport_id: str,
    version: int | None,
    provider: str,
    modality: str,
) -> tuple[Any, Any, str]:
    """Resolve a locked passport and its Mint owner before provider dispatch."""
    from app.domains.gateway.identity_lock_client import (
        IdentityLockError,
        identity_lock_client_from_config,
    )
    from app.domains.wallet.mint_accounts import resolve_mint_account
    from app.domains.wallet.mint_client import mint_client_from_config
    from app.domains.wallet.mint_stage import should_use_mint

    if modality != VIDEO:
        raise GatewayError(
            "Identity Lock is currently supported for video generations",
            status_code=422,
        )
    try:
        if not should_use_mint(user_id):
            raise GatewayError(
                "Identity Lock generations require Mint settlement", status_code=503
            )
        mint = mint_client_from_config()
        identity = identity_lock_client_from_config()
        if mint is None or identity is None:
            raise GatewayError(
                "Identity Lock generation services are not configured", status_code=503
            )
        payer = resolve_mint_account(session, user_id, None, client=mint)
        binding = identity.prepare(
            passport_id=passport_id,
            provider=provider,
            modality=modality,
            payer_account=payer,
            version=version,
        )
        return binding, mint, payer
    except GatewayError:
        raise
    except IdentityLockError as exc:
        raise GatewayError(exc.message, status_code=exc.status_code) from exc
    except Exception as exc:  # noqa: BLE001 - normalize the service boundary
        status = int(getattr(exc, "status_code", 502) or 502)
        message = str(getattr(exc, "message", "") or "identity preparation failed")
        raise GatewayError(message, status_code=status) from exc


def list_identity_options(session: Any, *, user_id: str) -> list[dict[str, Any]]:
    """Return exact locked passport heads selectable by this Menivor user."""
    from dataclasses import asdict

    from app.domains.gateway.identity_lock_client import (
        IdentityLockError,
        identity_lock_client_from_config,
    )
    from app.domains.wallet.mint_accounts import resolve_mint_account
    from app.domains.wallet.mint_client import mint_client_from_config
    from app.domains.wallet.mint_stage import should_use_mint

    try:
        if not should_use_mint(user_id):
            return []
        mint = mint_client_from_config()
        identity = identity_lock_client_from_config()
        if mint is None or identity is None:
            return []
        payer = resolve_mint_account(session, user_id, None, client=mint)
        return [asdict(option) for option in identity.list_locked(owner=payer)]
    except IdentityLockError as exc:
        raise GatewayError(exc.message, status_code=exc.status_code) from exc
    except Exception as exc:  # noqa: BLE001 - normalize the service boundary
        status = int(getattr(exc, "status_code", 502) or 502)
        message = str(getattr(exc, "message", "") or "identity selection failed")
        raise GatewayError(message, status_code=status) from exc


def _condition_video(
    prompt: str, image_url: str, conditioning: dict[str, Any]
) -> tuple[str, str]:
    """Map Identity Lock's portable video payload onto current adapters."""
    reference_images = conditioning.get("reference_images") or []
    if not isinstance(reference_images, list):
        reference_images = []
    reference = str(conditioning.get("avatar_ref") or "")
    if not reference and reference_images:
        reference = str(reference_images[0] or "")
    if not (image_url or reference):
        raise GatewayError(
            "this passport has no video reference image/avatar usable by Menivor",
            status_code=422,
        )
    additions: list[str] = []
    style = str(conditioning.get("style_prompt") or "").strip()
    if style:
        additions.append(style)
    directives = conditioning.get("text_directives") or []
    if isinstance(directives, list):
        additions.extend(str(item).strip() for item in directives if str(item).strip())
    negative = str(conditioning.get("negative_prompt") or "").strip()
    if negative:
        additions.append(f"Avoid: {negative}")
    effective_prompt = ". ".join(
        [part for part in [prompt.strip(), *additions] if part]
    )
    return effective_prompt, image_url or reference


_SETTLEMENT_INTENT_SCHEMA = "menivor.media-settlement-intent/v1"


def _settlement_error(exc: Exception, fallback: str) -> GatewayError:
    status = int(getattr(exc, "status_code", 502) or 502)
    message = str(getattr(exc, "message", "") or fallback)
    return GatewayError(message, status_code=status)


def _mint_client_or_raise() -> Any:
    from app.domains.wallet.mint_client import mint_client_from_config

    mint = mint_client_from_config()
    if mint is None:
        raise GatewayError("Mint is unavailable for the persisted settlement rail", status_code=502)
    return mint


def _settlement_intent(
    row: MediaJob, operation: str, amount_micros: int
) -> dict[str, Any]:
    suffix = {
        "hold.create": "hold",
        "hold.capture": "capture",
        "hold.release": "release",
    }[operation]
    return {
        "schema": _SETTLEMENT_INTENT_SCHEMA,
        "operation": operation,
        "idempotency_key": f"menivor:media:{row.id}:{suffix}",
        "amount_micros": int(amount_micros),
        "reference": str(row.settlement_request_id),
        "hold_id": str(row.mint_hold_id or ""),
    }


def _require_pending_intent(
    row: MediaJob, operation: str, amount_micros: int
) -> dict[str, Any]:
    expected = _settlement_intent(row, operation, amount_micros)
    stored = dict(row.settlement_intent or {})
    if stored != expected:
        raise GatewayError(
            "persisted Mint settlement intent does not match the requested replay",
            status_code=500,
        )
    return stored


def _reserve_job(
    session: Any,
    row: MediaJob,
    *,
    mint: Any = None,
    payer: str = "",
) -> None:
    """Choose one rail and durably reserve before any provider I/O.

    Mint writes a replayable reserve intent before the remote call. A lost
    response remains ``reserve_pending`` and can only replay the same row-bound
    operation; it can never fall back to the local wallet.
    """
    from app.domains.wallet.mint_stage import should_use_mint

    request_id = _correlation_id(row)
    outcome = str(row.settlement_outcome or "")
    if outcome == "held":
        return
    if outcome not in {"", "reserve_pending"}:
        raise GatewayError(
            f"cannot reserve media job from settlement outcome {outcome!r}",
            status_code=409,
        )

    if outcome == "reserve_pending":
        if row.settlement_rail != "mint":
            raise GatewayError("only Mint reservations may be pending", status_code=500)
        mint = mint or _mint_client_or_raise()
        payer = str(row.settlement_payer_account or "")
        if not payer:
            raise GatewayError("pending Mint reservation has no payer", status_code=500)
        intent = _require_pending_intent(row, "hold.create", row.held_cost_micros)
    else:
        use_mint = mint is not None or should_use_mint(row.user_id)
        row.settlement_request_id = request_id
        if not use_mint:
            row.settlement_rail = "local"
            row.settlement_payer_account = str(row.user_id)
            row.settlement_intent = {}
            _reserve(session, row.user_id, row.held_cost_micros, row.id)
            row.settlement_outcome = "held"
            session.flush()
            return

        mint = mint or _mint_client_or_raise()
        if not payer:
            from app.domains.wallet.mint_accounts import resolve_mint_account

            payer = resolve_mint_account(session, row.user_id, None, client=mint)
        row.settlement_rail = "mint"
        row.settlement_payer_account = str(payer)
        row.settlement_outcome = "reserve_pending"
        row.settlement_intent = _settlement_intent(
            row, "hold.create", row.held_cost_micros
        )
        session.commit()
        intent = dict(row.settlement_intent)

    try:
        hold = mint.create_hold(
            from_account=payer,
            amount_micros=int(intent["amount_micros"]),
            idem_key=str(intent["idempotency_key"]),
            ref=str(intent["reference"]) or None,
        )
        hold_id = str(hold.get("hold_id", "") or "")
        if not hold_id:
            raise GatewayError("Mint reserve returned no hold id", status_code=502)
    except GatewayError:
        raise
    except Exception as exc:  # noqa: BLE001 - retain pending intent for replay
        row.error = str(getattr(exc, "message", "") or "Mint reserve pending")
        session.commit()
        raise _settlement_error(exc, "Mint reserve failed") from exc

    row.mint_hold_id = hold_id
    row.settlement_outcome = "held"
    row.settlement_intent = {
        **intent,
        "hold_id": hold_id,
    }
    row.error = ""
    session.commit()


def _terminal_mint_operation(
    session: Any,
    row: MediaJob,
    *,
    operation: str,
    amount_micros: int,
) -> dict:
    target = "captured" if operation == "hold.capture" else "released"
    pending = "capture_pending" if operation == "hold.capture" else "release_pending"
    opposite = "released" if target == "captured" else "captured"
    opposite_pending = "release_pending" if pending == "capture_pending" else "capture_pending"
    outcome = str(row.settlement_outcome or "")
    if outcome == target:
        receipt = dict(row.settlement_receipt or {})
        if (
            not receipt
            or not row.settlement_attestation
            or int(row.settlement_verified_at_ms or 0) <= 0
        ):
            raise GatewayError(
                "terminal Mint outcome has no verified settlement evidence",
                status_code=500,
            )
        return receipt
    if outcome in {opposite, opposite_pending}:
        raise GatewayError(
            "refusing the opposite terminal operation for this Mint hold",
            status_code=409,
        )
    if outcome not in {"held", pending}:
        raise GatewayError(
            f"cannot {operation} from settlement outcome {outcome!r}",
            status_code=409,
        )
    if not row.mint_hold_id:
        raise GatewayError("Mint settlement has no durable hold id", status_code=500)

    if outcome == "held":
        row.settlement_outcome = pending
        row.settlement_intent = _settlement_intent(row, operation, amount_micros)
        session.commit()
    intent = _require_pending_intent(row, operation, amount_micros)
    mint = _mint_client_or_raise()
    try:
        if operation == "hold.capture":
            data, receipt = mint.capture_hold_with_receipt(
                str(intent["hold_id"]),
                int(intent["amount_micros"]),
                mint.treasury_account,
                str(intent["idempotency_key"]),
                str(intent["reference"]) or None,
            )
        else:
            data, receipt = mint.release_hold_with_receipt(
                str(intent["hold_id"]),
                int(intent["amount_micros"]),
                str(intent["idempotency_key"]),
                str(intent["reference"]) or None,
            )
        from app.config import config
        from app.domains.wallet.hold_settlement_attestation import (
            HoldSettlementExpected,
            verify_hold_settlement_attestation,
        )
        from app.domains.wallet.transfer_attestation import load_pinned_public_keys

        verified = verify_hold_settlement_attestation(
            data.get("attestation") if isinstance(data, dict) else None,
            HoldSettlementExpected(
                operation=operation,
                hold_id=str(intent["hold_id"]),
                payer_account=str(row.settlement_payer_account),
                payee_account=(mint.treasury_account if operation == "hold.capture" else ""),
                amount_micros=int(intent["amount_micros"]),
                idempotency_key=str(intent["idempotency_key"]),
                reference=str(intent["reference"]),
                receipt=receipt,
            ),
            load_pinned_public_keys(
                config.mint.get("attestation_public_keys_json", "")
            ),
        )
    except Exception as exc:  # noqa: BLE001 - the same intent is safe to replay
        pending_error = str(
            getattr(exc, "message", "") or f"Mint {operation} verification failed"
        )
        provider_error = str(row.error or "")
        row.error = (
            f"{provider_error}; settlement {pending}: {pending_error}"
            if provider_error
            else f"settlement {pending}: {pending_error}"
        )
        session.commit()
        raise _settlement_error(exc, f"Mint {operation} failed") from exc

    verified_at_ms = int(time.time() * 1000)
    row.settlement_receipt = dict(receipt)
    row.settlement_attestation = dict(verified.envelope)
    row.settlement_settled_at_ms = verified_at_ms
    row.settlement_verified_at_ms = verified_at_ms
    row.settlement_outcome = target
    if target == "captured":
        row.actual_cost_micros = int(amount_micros)
        # A capture that ultimately verified is a clean success: drop any
        # transient "settlement capture_pending" retry noise accumulated by
        # earlier attempts so a settled job does not surface a stale error.
        row.error = ""
    session.commit()
    return dict(receipt)


def _release_job(session: Any, row: MediaJob) -> None:
    if row.settlement_rail == "mint":
        _terminal_mint_operation(
            session,
            row,
            operation="hold.release",
            amount_micros=int(row.held_cost_micros),
        )
        return
    _release(session, row.user_id, row.held_cost_micros, row.id)
    row.settlement_outcome = "released"
    row.settlement_receipt = {}
    # Provider errors are re-raised by the endpoint. Commit the independent
    # local money terminal before that outer transaction can roll back.
    session.commit()


def _retain_ambiguous_submit(
    row: MediaJob, message: str, *, provider: str | None = None
) -> None:
    """Keep a reserved job recoverable when upstream acceptance is unknown."""
    if provider is not None:
        row.provider = provider
    row.status = "in_progress"
    row.error = f"submission outcome ambiguous: {message}"


def _settle_and_attest_identity(session: Any, row: MediaJob, actual: int) -> None:
    """Capture once, persist proof, then idempotently attest the output."""
    from app.domains.gateway.identity_lock_client import (
        IdentityBinding,
        IdentityLockError,
        identity_lock_client_from_config,
    )
    identity = identity_lock_client_from_config()
    if identity is None:
        raise GatewayError(
            "identity settlement services are unavailable", status_code=502
        )
    if (
        row.settlement_outcome != "captured"
        or not row.settlement_receipt
        or not row.settlement_attestation
        or int(row.settlement_verified_at_ms or 0) <= 0
    ):
        raise GatewayError(
            "identity attestation requires verified Mint capture evidence",
            status_code=503,
        )
    if row.identity_status != "attested":
        row.identity_status = "attestation_pending"
        session.commit()

    binding = IdentityBinding(
        passport_id=row.identity_passport_id,
        version=row.identity_version,
        content_digest=row.identity_content_digest,
        provider=row.identity_provider,
        modality=row.modality,
        conditioning={},
    )
    try:
        record = identity.attest(
            binding,
            output_ref=row.output_url,
            asset_hash=None,
            request_id=row.settlement_request_id,
            payer_account=row.settlement_payer_account,
            receipt=dict(row.settlement_receipt or {}),
            settled_at_ms=row.settlement_settled_at_ms,
        )
    except IdentityLockError as exc:
        raise GatewayError(exc.message, status_code=exc.status_code) from exc
    row.identity_provenance_id = str(record.get("id", "") or "")
    if not row.identity_provenance_id:
        raise GatewayError(
            "Identity Lock attestation returned no record id", status_code=502
        )
    if (
        str(record.get("passport_content_digest", "") or "")
        != row.identity_content_digest
    ):
        raise GatewayError("Identity Lock attestation digest mismatch", status_code=502)
    row.identity_status = "attested"


def _meter_settled_job(row: MediaJob, actual: int) -> None:
    """Report one captured media job to Railyard Rago (best-effort, opt-in).

    A no-op unless ``RAILYARD_RAGO_URL`` + ``RAILYARD_RAGO_API_KEY`` are set.
    Transaction ids are derived from the job id, so a settlement resumed by
    reconciliation is metered once. Never fails or delays settlement: the
    wallet / Mint capture above stays the money source of truth.
    """
    try:
        from app.integrations.railyard import meter_render

        meter_render(
            job_id=str(row.id),
            owner_key=str(row.user_id or ""),
            credits_micros=int(actual),
            rail=str(row.settlement_rail or "local"),
            job_kind=f"media_{row.modality or 'unknown'}",
        )
    except Exception as exc:  # noqa: BLE001 - metering is best-effort only
        logger.debug(f"railyard media metering skipped for job {row.id}: {exc}")


def _settle_job(session: Any, row: MediaJob, actual: int) -> None:
    if row.settlement_rail == "mint":
        _terminal_mint_operation(
            session, row, operation="hold.capture", amount_micros=actual
        )
    else:
        _settle(session, row.user_id, row.held_cost_micros, actual, row.id)
        row.settlement_outcome = "captured"
        row.settlement_receipt = {}
    if row.settlement_outcome == "captured":
        _meter_settled_job(row, actual)
    if row.identity_passport_id:
        _settle_and_attest_identity(session, row, actual)


def _provider_failed_then_release(
    session: Any, row: MediaJob, message: str
) -> None:
    """Persist provider failure first, then independently finish settlement."""
    row.status = "failed"
    row.error = message
    session.commit()
    try:
        _release_job(session, row)
    except GatewayError:
        # The provider-terminal fact is durable. The exact release intent is
        # also durable and reconciliation must replay it, never capture.
        return
    # HTTP handlers propagate the provider error after this function returns.
    # Their context manager therefore cannot be relied on to commit code after
    # ``yield``. Persist the successful local/Mint release here so a definitive
    # provider rejection never leaves a committed reservation stranded.
    session.commit()


def _provider_completed_then_capture(
    session: Any,
    row: MediaJob,
    *,
    output_url: str,
    actual_micros: int,
) -> None:
    """Persist provider output first, then independently capture its exact cost."""
    row.output_url = output_url
    row.actual_cost_micros = int(actual_micros)
    row.status = "completed"
    row.error = ""
    session.commit()
    _settle_job(session, row, int(actual_micros))
    row.error = ""
    session.flush()


def _resume_terminal_settlement(session: Any, row: MediaJob) -> None:
    outcome = str(row.settlement_outcome or "")
    if row.status == "completed":
        if outcome not in {"captured"}:
            _settle_job(session, row, int(row.actual_cost_micros))
        elif row.identity_passport_id and row.identity_status != "attested":
            _settle_and_attest_identity(session, row, int(row.actual_cost_micros))
    elif row.status in {"failed", "cancelled"} and outcome != "released":
        _release_job(session, row)


def _model_or_raise(model_id: str, want: str) -> MediaModel:
    m = get_model(model_id)
    if m is None:
        gone = retired(model_id)
        if gone is not None:
            # QM1.1: a model the vendor shut down stays in the catalogue history; say what replaced it.
            raise GatewayError(f"{model_id!r} was retired on {gone.retired_on}; use {gone.successor!r}",
                               status_code=410)
        raise GatewayError(f"unknown model {model_id!r}", status_code=404)
    if m.modality != want:
        raise GatewayError(
            f"{model_id!r} is a {m.modality} model, not {want}", status_code=422
        )
    # MO1 licence gate: every gateway call is wallet-funded (paid), so a model
    # with non-commercial, research-only or unrecorded weights fails closed here,
    # before any reserve or provider call.
    from app.domains.routing.license_class import LicenseError, assert_model_sellable

    try:
        assert_model_sellable(m.id)
    except LicenseError as exc:
        raise GatewayError(f"{exc}; choose another model", status_code=403) from exc
    return m


def _provider_request(
    model: MediaModel,
    *,
    correlation_id: str,
    prompt: str,
    cost_micros: int,
    duration_seconds: int = 0,
    aspect_ratio: str = "",
    image_url: str = "",
    instrumental: bool = False,
    input_refs: Sequence[str] = (),
    generate_audio: bool | None = None,
) -> ProviderRequestV1:
    """The versioned provider request.

    ``input_refs`` (already-resolved URLs in @ImageN order) wins over ``image_url``.
    Rows that take a reference list (``"images"`` in ``inputs``) get
    ``image_mode="reference"`` so the adapter sends every ref with its reference
    role; every other row treats the first ref as the first frame.
    """
    quantity = duration_seconds if model.modality == VIDEO else 1
    refs = tuple(u for u in input_refs if u) or ((image_url,) if image_url else ())
    parameters: dict[str, Any] = {
        "estimated_cost_micros": int(cost_micros),
        "cost_source": "catalog_estimate",
        "unit": model.unit,
        "quantity_units": max(0, int(quantity)),
        "instrumental": bool(instrumental),
    }
    if "images" in model.inputs:
        parameters["image_mode"] = "reference"
    if generate_audio is not None:
        parameters["generate_audio"] = bool(generate_audio)  # models with native audio (Seedance 2.0)
    if model.resolution:
        parameters["resolution"] = model.resolution
    return ProviderRequestV1(
        provider_key=model.provider,
        model_ref=model.model_ref,
        correlation_id=correlation_id,
        modality=model.modality,
        prompt=prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        input_refs=refs,
        parameters=parameters,
    )


def reference_inputs(
    m: MediaModel, references: Sequence[Reference], image_url: str = ""
) -> tuple[str, tuple[str, ...]]:
    """Map role-tagged references onto ``(image_url, input_refs)`` for model ``m``.

    Raises a 400 :class:`GatewayError` (plain message) when the model cannot take
    them: text-only rows take none, single-image rows take only a first frame,
    reference rows take up to four. References must already be public https URLs
    (storage keys are presigned by the caller after an ownership check).
    """
    refs = ordered_references(references)
    if not refs:
        return image_url, ()
    if image_url:
        raise GatewayError(
            "send the first frame either as image_url or as a first_frame reference, not both",
            status_code=400,
        )
    if any(not public_https_url(r.url) for r in refs):
        raise GatewayError("reference images must be public https URLs", status_code=400)
    first = next((r.url for r in refs if r.role == ROLE_FIRST_FRAME), "")
    if "images" in m.inputs:
        return first, tuple(r.url for r in refs)
    if "image" in m.inputs:
        if len(refs) != 1 or not first:
            raise GatewayError(
                f"{m.id} takes one image, the first frame; use a reference-to-video model "
                "for identity or style references",
                status_code=400,
            )
        return first, ()
    raise GatewayError(
        f"{m.id} is a text-to-video model and does not take reference images; "
        "choose an image-to-video model such as bytedance/seedance-2.0-i2v",
        status_code=400,
    )


def _provider_error_status(exc: ProviderExecutionException) -> int:
    error = exc.error
    # Upstream poll authentication/authorization is a provider availability
    # problem, never the caller's HTTP authentication status.
    if error.phase == "poll":
        return 502
    if error.provider_code.isdigit():
        status = int(error.provider_code)
        if 400 <= status <= 599:
            return status
    if error.category == "auth":
        return 503
    if error.category in {"validation", "policy"}:
        return 400
    return 502


def _retain_provider_exception(row: MediaJob, exc: ProviderExecutionException) -> bool:
    """Return true when submit acceptance is uncertain and the hold must remain."""
    if exc.error.acceptance == "not_accepted":
        return False
    _retain_ambiguous_submit(row, exc.error.message)
    return True


# --------------------------------------------------------------------------- #
# Video — async (returns a job to poll), OpenRouter /videos parity
# --------------------------------------------------------------------------- #
def create_video(
    session: Any,
    *,
    user_id: str,
    model: str,
    prompt: str,
    duration: int = 5,
    aspect_ratio: str = "9:16",
    image_url: str = "",
    identity_passport_id: str = "",
    identity_version: int | None = None,
    session_http: Any = None,
    references: Sequence[Reference] = (),
) -> MediaJob:
    """Reserve the wallet, submit the video job upstream, persist + return it.

    ``references`` are role-tagged, already-resolved https URLs; see
    :func:`reference_inputs` for which models take them.
    """
    m = _model_or_raise(model, VIDEO)
    if image_url and not public_https_url(image_url):
        raise GatewayError("image_url must be a public https URL", status_code=400)
    image_url, input_refs = reference_inputs(m, references, image_url)
    if input_refs and prism_client_from_config() is not None:
        raise GatewayError(
            "multi-reference video is not available on this deployment yet", status_code=422
        )
    seconds = max(1, min(int(duration), m.max_seconds or int(duration)))
    if m.provider == "kling-fal":
        from app.domains.gateway.fal_duration import DurationUnsupported, check_seconds

        try:
            # H4: refuse a length the fal endpoint cannot render before any
            # reservation, wallet hold or provider call.
            check_seconds(m.model_ref, seconds)
        except DurationUnsupported as exc:
            raise GatewayError(str(exc), status_code=exc.status_code) from exc
    cost = seconds * m.price_micros

    identity_binding = None
    identity_mint = None
    identity_payer = ""
    if identity_passport_id:
        identity_binding, identity_mint, identity_payer = _prepare_identity(
            session,
            user_id=user_id,
            passport_id=identity_passport_id,
            version=identity_version,
            provider=m.provider,
            modality=VIDEO,
        )
        prompt, image_url = _condition_video(
            prompt, image_url, identity_binding.conditioning
        )

    row = MediaJob(
        user_id=user_id,
        model=m.id,
        modality=VIDEO,
        provider=m.provider,
        prompt=prompt,
        seconds=seconds,
        held_cost_micros=cost,
        identity_passport_id=(identity_binding.passport_id if identity_binding else ""),
        identity_version=(identity_binding.version if identity_binding else 0),
        identity_content_digest=(
            identity_binding.content_digest if identity_binding else ""
        ),
        identity_provider=(identity_binding.provider if identity_binding else ""),
        identity_status=("resolved" if identity_binding else "none"),
    )
    session.add(row)
    session.flush()
    correlation_id = _correlation_id(row)
    _reserve_job(
        session,
        row,
        mint=identity_mint if identity_binding else None,
        payer=identity_payer,
    )

    try:
        prism = prism_client_from_config()
        if prism is not None:
            result = prism.generate(
                model=m.id,
                prompt=prompt,
                modality=VIDEO,
                duration_seconds=seconds,
                aspect_ratio=aspect_ratio,
                image_url=image_url,
                max_cost_micros=cost,
                correlation_id=correlation_id,
            )
            row.provider = f"prism:{result.get('provider', 'unknown')}"
            row.provider_ref = str(result.get("id", "") or "")
            if str(result.get("correlation_id", "") or "") != correlation_id:
                raise PrismClientError(
                    502,
                    "Prism changed the request correlation id",
                    acceptance="unknown",
                )
            raw_cost = result.get("cost_micros")
            try:
                reported_cost = cost if raw_cost is None else int(raw_cost)
            except (TypeError, ValueError) as exc:
                raise PrismClientError(
                    502, "Prism reported an invalid cost", acceptance="unknown"
                ) from exc
            if reported_cost < 0 or reported_cost > cost:
                raise PrismClientError(
                    502,
                    "Prism reported a cost outside the reserved cap",
                    acceptance="unknown",
                )
            row.model = str(result.get("model", m.id) or m.id)
            row.actual_cost_micros = reported_cost
            row.status = (
                "completed" if result.get("status") == "completed" else "in_progress"
            )
            row.output_url = str(result.get("output_url", "") or "")
            if row.status == "completed":
                _provider_completed_then_capture(
                    session,
                    row,
                    output_url=row.output_url,
                    actual_micros=reported_cost,
                )
                _metric_job(VIDEO, row.provider, "completed")
                _metric_debit(reported_cost)
            session.flush()
            return row

        execution = MediaProviderExecutor(session_http=session_http).submit(
            _provider_request(
                m,
                correlation_id=correlation_id,
                prompt=prompt,
                cost_micros=cost,
                duration_seconds=seconds,
                aspect_ratio=aspect_ratio,
                image_url=image_url,
                input_refs=input_refs,
            )
        )
    except GatewayError as exc:
        if row.status != "completed":
            _provider_failed_then_release(session, row, str(exc))
        raise
    except PrismClientError as exc:
        if exc.may_have_been_accepted:
            _retain_ambiguous_submit(
                row,
                exc.message,
                provider=(
                    row.provider
                    if row.provider.startswith("prism:")
                    else "prism:pending"
                ),
            )
            session.commit()
        else:
            _provider_failed_then_release(session, row, exc.message)
        session.flush()
        raise GatewayError(exc.message, status_code=exc.status_code) from exc
    except ProviderExecutionException as exc:
        if _retain_provider_exception(row, exc):
            session.commit()
        else:
            _provider_failed_then_release(session, row, exc.error.message)
        session.flush()
        raise GatewayError(
            f"upstream submit failed: {exc.error.message}",
            status_code=_provider_error_status(exc),
        ) from exc
    except (KlingError,) as exc:
        if exc.may_have_been_accepted:
            _retain_ambiguous_submit(row, str(exc))
            session.commit()
        else:
            _provider_failed_then_release(session, row, str(exc))
        session.flush()
        raise GatewayError(
            f"upstream submit failed: {exc}", status_code=502 if exc.retryable else 400
        ) from exc

    row.provider_execution = execution.to_dict()
    row.provider_ref = execution.handle.run_id
    row.status_url = execution.handle.status_url
    row.response_url = execution.handle.response_url
    row.status = "in_progress"
    session.flush()
    return row


def _submit_video_upstream(
    m: MediaModel,
    *,
    prompt: str,
    seconds: int,
    aspect_ratio: str,
    image_url: str,
    session_http: Any,
    api_key: str = "",
) -> tuple[str, str, str]:
    """Compatibility tuple over the public versioned execution boundary."""
    result = MediaProviderExecutor(api_key=api_key, session_http=session_http).submit(
        _provider_request(
            m,
            correlation_id="legacy-direct-submit",
            prompt=prompt,
            cost_micros=seconds * m.price_micros,
            duration_seconds=seconds,
            aspect_ratio=aspect_ratio,
            image_url=image_url,
        )
    )
    return result.handle.run_id, result.handle.status_url, result.handle.response_url


# --------------------------------------------------------------------------- #
# Audio — async (returns a job to poll), flat per-generation price.
# Polling reuses ``poll_video`` (it dispatches by provider); only submit differs.
# --------------------------------------------------------------------------- #
def create_audio(
    session: Any,
    *,
    user_id: str,
    model: str,
    prompt: str,
    instrumental: bool = False,
    session_http: Any = None,
) -> MediaJob:
    """Reserve the wallet, submit the audio job upstream, persist + return it."""
    m = _model_or_raise(model, AUDIO)
    cost = m.price_micros  # flat per-generation

    row = MediaJob(
        user_id=user_id,
        model=m.id,
        modality=AUDIO,
        provider=m.provider,
        prompt=prompt,
        seconds=0,
        held_cost_micros=cost,
    )
    session.add(row)
    session.flush()
    correlation_id = _correlation_id(row)
    _reserve_job(session, row)

    try:
        execution = MediaProviderExecutor(session_http=session_http).submit(
            _provider_request(
                m,
                correlation_id=correlation_id,
                prompt=prompt,
                cost_micros=cost,
                instrumental=instrumental,
            )
        )
    except GatewayError as exc:
        _provider_failed_then_release(session, row, str(exc))
        raise
    except ProviderExecutionException as exc:
        if _retain_provider_exception(row, exc):
            session.commit()
        else:
            _provider_failed_then_release(session, row, exc.error.message)
        session.flush()
        raise GatewayError(
            f"upstream submit failed: {exc.error.message}",
            status_code=_provider_error_status(exc),
        ) from exc
    except KlingError as exc:
        if exc.may_have_been_accepted:
            _retain_ambiguous_submit(row, str(exc))
            session.commit()
        else:
            _provider_failed_then_release(session, row, str(exc))
        session.flush()
        raise GatewayError(
            f"upstream submit failed: {exc}", status_code=502 if exc.retryable else 400
        ) from exc

    row.provider_execution = execution.to_dict()
    row.provider_ref = execution.handle.run_id
    row.status_url = execution.handle.status_url
    row.response_url = execution.handle.response_url
    row.status = "in_progress"
    session.flush()
    return row


def _submit_audio_upstream(
    m: MediaModel, *, prompt: str, instrumental: bool, session_http: Any
) -> tuple[str, str, str]:
    """Compatibility tuple over the public versioned execution boundary."""
    result = MediaProviderExecutor(session_http=session_http).submit(
        _provider_request(
            m,
            correlation_id="legacy-direct-audio-submit",
            prompt=prompt,
            cost_micros=m.price_micros,
            instrumental=instrumental,
        )
    )
    return result.handle.run_id, result.handle.status_url, result.handle.response_url


def poll_video(
    session: Any, *, user_id: str, job_id: str, session_http: Any = None
) -> MediaJob:
    """Advance a persisted media job (video or audio); settle/refund on a terminal result."""
    row = session.get(MediaJob, job_id)
    if row is None or str(row.user_id) != str(user_id):
        raise GatewayError("job not found", status_code=404)
    if row.settlement_outcome == "reserve_pending":
        _reserve_job(session, row)
    if row.status in ("completed", "failed"):
        _resume_terminal_settlement(session, row)
        return row

    if row.provider.startswith("prism:"):
        try:
            prism = prism_client_from_config()
            if prism is None:
                raise PrismClientError(503, "Prism is no longer configured")
            result = (
                prism.generation(
                    row.provider_ref, correlation_id=_correlation_id(row)
                )
                if row.provider_ref
                else prism.generation_by_correlation(_correlation_id(row))
            )
        except PrismClientError as exc:
            # An accepted provider request is not proven failed merely because a
            # replica cannot currently resolve its durable handle. Retain the
            # hold and let reconciliation retry; releasing here could make a
            # successful provider generation free.
            status_code = 503 if exc.status_code == 404 else exc.status_code
            raise GatewayError(exc.message, status_code=status_code) from exc

        status = str(result.get("status", "running") or "running")
        if str(result.get("correlation_id", "") or "") != _correlation_id(row):
            raise GatewayError(
                "Prism poll changed the request correlation id", status_code=502
            )
        recovered_id = str(result.get("id", "") or "")
        if not recovered_id:
            raise GatewayError("Prism recovery returned no generation id", status_code=502)
        if row.provider_ref and recovered_id != row.provider_ref:
            raise GatewayError("Prism recovery changed the generation id", status_code=502)
        row.provider_ref = recovered_id
        row.provider = f"prism:{result.get('provider', 'unknown')}"
        row.error = ""
        if status == "completed":
            raw_cost = result.get("cost_micros")
            actual = int(row.actual_cost_micros if raw_cost is None else raw_cost)
            if actual < 0 or actual > row.held_cost_micros:
                raise GatewayError(
                    "Prism reported a cost outside the reserved cap", status_code=502
                )
            output_url = str(result.get("output_url", "") or "")
            if not output_url:
                raise GatewayError(
                    "Prism completed without an output URL", status_code=502
                )
            row.output_url = output_url
            row.actual_cost_micros = actual
            _provider_completed_then_capture(
                session, row, output_url=output_url, actual_micros=actual
            )
            _metric_job(row.modality, row.provider, "completed")
            _metric_debit(actual)
        elif status == "failed":
            _provider_failed_then_release(
                session,
                row,
                str(result.get("error", "") or "Prism generation failed"),
            )
            _metric_job(row.modality, row.provider, "failed")
        else:
            row.status = "in_progress"
        session.flush()
        return row

    if not row.provider_ref:
        raise GatewayError(
            row.error or "provider submission outcome is ambiguous",
            status_code=503,
        )

    try:
        terminal, output_url, failure = _poll_video_upstream(
            row, session_http=session_http
        )
    except ProviderExecutionException as exc:
        row.status = "in_progress"
        row.error = exc.error.message
        session.flush()
        raise GatewayError(
            f"upstream poll failed: {exc.error.message}",
            status_code=_provider_error_status(exc),
        ) from exc
    except KlingError as exc:
        row.status = "in_progress"
        row.error = str(exc)
        session.flush()
        raise GatewayError(f"upstream poll failed: {exc}", status_code=502) from exc

    if terminal and output_url:
        actual = row.held_cost_micros  # fixed per-second price
        _provider_completed_then_capture(
            session, row, output_url=output_url, actual_micros=actual
        )
        _metric_job(row.modality, row.provider, "completed")
        _metric_debit(actual)  # success-only billing
    elif terminal:  # terminal but failed
        _provider_failed_then_release(session, row, failure or "upstream failed")
        _metric_job(
            row.modality, row.provider, "failed"
        )  # no debit — a failed job is free
    else:
        row.status = "in_progress"
    session.flush()
    return row


def _cancel_upstream(
    row: MediaJob, *, session_http: Any = None, api_key: str = ""
) -> None:
    """Best-effort provider-side cancellation for a still-running handle.

    Reconstructs the immutable submit-time handle and asks the executor to cancel
    it upstream (kling-fal/runway/luma/wan expose a real cancel; veo/minimax/suno
    are abandoned locally). A provider whose cancel call fails must never block the
    local abandon + hold release, so upstream errors are swallowed here — the money
    terminal is driven by the caller regardless.
    """
    if not row.provider_execution:
        # Submission never produced a durable handle (ambiguous/never-accepted):
        # there is nothing to cancel upstream, only to release locally.
        return
    stored = ProviderResultV1.from_dict(row.provider_execution)
    handle = stored.handle
    if handle.state in {"COMPLETED", "FAILED", "CANCELLED"}:
        return
    if handle.provider_key != row.provider or handle.run_id != row.provider_ref:
        raise GatewayError("stored provider execution identity mismatch", status_code=500)
    try:
        result = MediaProviderExecutor(
            api_key=api_key, session_http=session_http
        ).cancel(handle)
    except ProviderExecutionException:
        # Upstream cancel is advisory; a failure to reach the provider must not
        # prevent us from stopping tracking and releasing the caller's hold.
        return
    row.provider_execution = result.to_dict()


def cancel_video(
    session: Any, *, user_id: str, job_id: str, session_http: Any = None
) -> MediaJob:
    """Cancel a still-running media job: stop tracking upstream, release the hold.

    Success-only billing means a cancelled job is free: the wallet/Mint hold is
    released, never captured. Idempotent — cancelling an already-terminal job
    replays the durable settlement terminal without charging. A completed job
    cannot be cancelled (its work — and cost — already happened)."""
    row = session.get(MediaJob, job_id)
    if row is None or str(row.user_id) != str(user_id):
        raise GatewayError("job not found", status_code=404)

    # A reservation that never confirmed must be resolved before it can be
    # released, so cancel can never strand a pending hold.
    if row.settlement_outcome == "reserve_pending":
        _reserve_job(session, row)

    if row.status == "completed":
        raise GatewayError(
            "completed generations cannot be cancelled", status_code=409
        )
    if row.status in {"failed", "cancelled"}:
        # Idempotent: finish any interrupted release, then return the terminal.
        _resume_terminal_settlement(session, row)
        session.flush()
        return row

    _cancel_upstream(row, session_http=session_http)

    row.status = "cancelled"
    row.error = "cancelled by user"
    session.commit()
    try:
        _release_job(session, row)
    except GatewayError:
        # The provider-terminal fact is durable and the exact release intent is
        # persisted; reconciliation must replay it (never capture). The job is
        # already cancelled from the caller's perspective.
        session.flush()
        return row
    session.commit()
    _metric_job(row.modality, row.provider, "cancelled")
    return row


def run_pending_reconciliation(
    *, limit: int = 100, session_factory: Any = None
) -> dict[str, int]:
    """Advance a bounded batch of unfinished gateway jobs after restarts.

    The normal client poll and this sweep call the same idempotent settlement
    path. A transient provider failure leaves the row and wallet hold intact for
    a later pass; one bad job never prevents recovery of the remaining batch.
    """
    if session_factory is None:
        from app.models.db.base import get_session

        session_factory = get_session

    summary = {
        "scanned": 0,
        "advanced": 0,
        "completed": 0,
        "failed": 0,
        "errored": 0,
    }
    with session_factory() as session:
        from sqlalchemy import or_

        rows = (
            session.query(MediaJob)
            .filter(
                or_(
                    MediaJob.status.notin_(("completed", "failed", "cancelled")),
                    MediaJob.settlement_outcome.in_(
                        (
                            "reserve_pending",
                            "held",
                            "capture_pending",
                            "release_pending",
                        )
                    ),
                    MediaJob.identity_status == "attestation_pending",
                )
            )
            .order_by(MediaJob.created_at.asc(), MediaJob.id.asc())
            .limit(max(1, min(500, int(limit))))
            .all()
        )
        for row in rows:
            summary["scanned"] += 1
            before = row.status
            try:
                current = poll_video(session, user_id=row.user_id, job_id=row.id)
            except Exception:  # noqa: BLE001 - one provider must not poison sweep
                summary["errored"] += 1
                continue
            if current.status != before:
                summary["advanced"] += 1
            if current.status == "completed":
                summary["completed"] += 1
            elif current.status == "failed":
                summary["failed"] += 1
    return summary


def _poll_video_upstream(
    row: MediaJob, *, session_http: Any, api_key: str = ""
) -> tuple[bool, str, str]:
    """Advance one shared provider handle and retain its versioned snapshot."""
    if row.provider_execution:
        stored = ProviderResultV1.from_dict(row.provider_execution)
        handle = stored.handle
        if handle.provider_key != row.provider or handle.run_id != row.provider_ref:
            raise GatewayError("stored provider execution identity mismatch", status_code=500)
    else:
        # Dual-read migration for jobs accepted before provider-handle/v1.
        model = get_row(row.model)  # the row the job was accepted on, even if it has since retired
        if model is None or model.provider != row.provider:
            raise GatewayError(
                "legacy provider handle cannot be resolved safely", status_code=503
            )
        handle = ProviderHandleV1(
            provider_key=row.provider,
            model_ref=model.model_ref,
            run_id=row.provider_ref,
            state="IN_PROGRESS",
            status_url=row.status_url,
            response_url=row.response_url,
            opaque={
                "modality": row.modality,
                "estimated_cost_micros": int(row.held_cost_micros),
                "cost_source": "legacy",
                "unit": model.unit,
                "quantity_units": row.seconds if row.modality == VIDEO else 1,
            },
        )

    result = MediaProviderExecutor(api_key=api_key, session_http=session_http).poll(handle)
    row.provider_execution = result.to_dict()
    row.status_url = result.handle.status_url
    row.response_url = result.handle.response_url
    if result.state == "COMPLETED":
        return True, result.outputs[0].reference, ""
    if result.state in {"FAILED", "CANCELLED"}:
        return True, "", result.error.message if result.error is not None else "upstream failed"
    return False, "", ""


# --------------------------------------------------------------------------- #
# Image — synchronous (returns the image), OpenRouter /images parity
# --------------------------------------------------------------------------- #
def create_image(
    session: Any,
    *,
    user_id: str,
    model: str,
    prompt: str,
    session_http: Any = None,
) -> dict:
    """Charge the wallet + call the image model synchronously; return the image url.

    Dispatches by provider to a real sync image backend (fal.ai or OpenAI). Success-
    only billing: any upstream failure refunds the reservation."""
    m = _model_or_raise(model, IMAGE)

    row = MediaJob(
        user_id=user_id,
        model=m.id,
        modality=IMAGE,
        provider=m.provider,
        prompt=prompt,
        held_cost_micros=m.price_micros,
        status="in_progress",
    )
    session.add(row)
    session.flush()
    correlation_id = _correlation_id(row)
    _reserve_job(session, row)
    try:
        prism = prism_client_from_config()
        if prism is not None:
            result = prism.generate(
                model=m.id,
                prompt=prompt,
                modality=IMAGE,
                max_cost_micros=m.price_micros,
                correlation_id=correlation_id,
            )
            row.provider = f"prism:{result.get('provider', 'unknown')}"
            row.provider_ref = str(result.get("id", "") or "")
            if str(result.get("correlation_id", "") or "") != correlation_id:
                raise PrismClientError(
                    502,
                    "Prism changed the request correlation id",
                    acceptance="unknown",
                )
            if result.get("status") != "completed" or not result.get("output_url"):
                raise PrismClientError(
                    502,
                    "Prism did not complete the synchronous image",
                    acceptance="unknown",
                )
            raw_cost = result.get("cost_micros")
            try:
                actual = m.price_micros if raw_cost is None else int(raw_cost)
            except (TypeError, ValueError) as exc:
                raise PrismClientError(
                    502, "Prism reported an invalid cost", acceptance="unknown"
                ) from exc
            if actual < 0 or actual > m.price_micros:
                raise PrismClientError(
                    502,
                    "Prism reported a cost outside the reserved cap",
                    acceptance="unknown",
                )
            url = str(result["output_url"])
            settled_model = str(result.get("model", m.id) or m.id)
            settled_provider = row.provider
        else:
            execution = MediaProviderExecutor(session_http=session_http).submit(
                _provider_request(
                    m,
                    correlation_id=correlation_id,
                    prompt=prompt,
                    cost_micros=m.price_micros,
                )
            )
            row.provider_execution = execution.to_dict()
            row.provider_ref = execution.handle.run_id
            url = execution.outputs[0].reference
            actual = execution.cost.cost_micros
            settled_model = m.id
            settled_provider = m.provider
    except GatewayError as exc:
        if row.status != "completed":
            _provider_failed_then_release(session, row, str(exc))
        _metric_job(IMAGE, m.provider, "failed")  # no debit
        raise
    except PrismClientError as exc:
        if exc.may_have_been_accepted:
            _retain_ambiguous_submit(
                row,
                exc.message,
                provider=(
                    row.provider
                    if row.provider.startswith("prism:")
                    else "prism:pending"
                ),
            )
            session.commit()
        else:
            _provider_failed_then_release(session, row, exc.message)
            _metric_job(IMAGE, "prism", "failed")
        session.flush()
        raise GatewayError(exc.message, status_code=exc.status_code) from exc
    except ProviderExecutionException as exc:
        if _retain_provider_exception(row, exc):
            session.commit()
        else:
            _provider_failed_then_release(session, row, exc.error.message)
            _metric_job(IMAGE, m.provider, "failed")
        session.flush()
        raise GatewayError(
            f"image generation failed: {exc.error.message}",
            status_code=_provider_error_status(exc),
        ) from exc
    except KlingError as exc:
        if exc.may_have_been_accepted:
            _retain_ambiguous_submit(row, str(exc))
            session.commit()
        else:
            _provider_failed_then_release(session, row, str(exc))
        _metric_job(IMAGE, m.provider, "failed")  # no debit
        raise GatewayError(
            f"image generation failed: {exc}", status_code=502 if exc.retryable else 400
        ) from exc
    row.model = settled_model
    row.provider = settled_provider
    _provider_completed_then_capture(
        session, row, output_url=url, actual_micros=actual
    )
    _metric_job(IMAGE, settled_provider, "completed")
    _metric_debit(actual)  # success-only billing
    return {
        "id": row.id,
        "model": settled_model,
        "modality": IMAGE,
        "status": "completed",
        "url": url,
        "cost_micros": actual,
    }


def _generate_image_upstream(
    m: MediaModel, *, prompt: str, session_http: Any, api_key: str = ""
) -> str:
    """Compatibility string over the public versioned execution boundary."""
    result = MediaProviderExecutor(api_key=api_key, session_http=session_http).submit(
        _provider_request(
            m,
            correlation_id="legacy-direct-image-submit",
            prompt=prompt,
            cost_micros=m.price_micros,
        )
    )
    return result.outputs[0].reference
