"""Character LoRA training as an async ``Job(kind="character_lora")``.

A per-character LoRA train is minutes of GPU, so — exactly like B-roll studio
generation — it runs as its own Celery job on the ``generation`` queue and this
module is the **service delegate** the task calls:

    POST /characters/{id}/train -> Job(kind="character_lora") -> train_character_lora_task
                                                              │
                            run_character_lora_training ──────┘  (this module)
                            presign owned refs -> lora_train adapter submit/poll
                            -> rehost .safetensors -> Character.lora_ref -> done

Two entry points (mirroring ``broll.service``):

* :func:`run_character_lora_training` — load the job's params, presign the
  creator's OWN reference keys (short-lived signed GETs, SSRF §8), drive the
  ``lora_train`` provider adapter submit→poll to terminal, rehost the produced
  ``.safetensors`` to R2 under ``characters/{id}/lora/{uuid}.safetensors``, write
  the key onto ``Character.lora_ref`` (so future shots auto-inject it), and mark
  the job complete (``result_key`` = the LoRA key). Raises on hard failure so the
  task's ``on_failure`` records the cause + refunds.
* :func:`refund_character_lora_training` — idempotently return the debited
  credits on failure (``params['refunded']`` guard — never double-refunds).

Params persisted on the ``Job`` row::

    {"character_id", "reference_keys", "steps", "rank", "base_model",
     "credits_cost", "workspace_id"?, "refunded"?}
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from loguru import logger

from app.domains.routing.base import RUN_COMPLETED, ProviderRun

_LORA_CAPABILITY: str = "lora_train"
_LORA_CONTENT_TYPE: str = "application/octet-stream"
_REF_PRESIGN_TTL_S: int = 900
_MIN_REFERENCES: int = 1
_POLL_INTERVAL_S: float = 5.0
_MAX_POLLS: int = 240  # ~20 min ceiling at 5s cadence


def _load_job_context(job_id: str) -> tuple[str, dict[str, Any]] | None:
    """Return ``(user_id, params)`` for a job, or ``None`` if it is gone."""
    from app.models.db.base import get_session
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        job = JobRepository(session).get(job_id)
        if job is None:
            return None
        return job.user_id, dict(job.params or {})


def _presign_reference_urls(reference_keys: list[str]) -> list[str]:
    """Mint short-lived signed GETs for the creator's OWN reference objects.

    Ownership was validated at the controller before enqueue, so here we only
    presign OUR OWN bucket keys — never a raw client URL (SSRF §8).
    """
    from app.platform.storage.r2 import get_r2_client

    client = get_r2_client()
    urls: list[str] = []
    for key in reference_keys:
        key = str(key or "").strip()
        if not key:
            continue
        urls.append(client.presign_get(key, expires=_REF_PRESIGN_TTL_S))
    return urls


def _resolve_adapter():
    """Resolve the registered ``lora_train`` provider adapter from the registry."""
    from app.domains.routing.base import registry as default_registry
    from app.domains.routing.runtime import ensure_adapters_registered

    ensure_adapters_registered()
    adapter = default_registry.get(_LORA_CAPABILITY)
    if adapter is None:
        raise RuntimeError("character_lora: no lora_train provider is configured")
    return adapter


def drive_training(
    adapter: Any,
    request: dict,
    snapshot: dict,
    correlation_id: str,
    *,
    sleep_fn: Any = None,
    max_polls: int = _MAX_POLLS,
) -> ProviderRun:
    """Drive an adapter submit→poll loop to a terminal run (pure, injectable).

    Kept free of DB/R2 so it is unit-testable with a fake adapter. Raises
    ``RuntimeError`` if the run terminates non-completed or never reaches a
    terminal state within ``max_polls`` cycles.
    """
    sleep_fn = sleep_fn or time.sleep
    run = adapter.submit(request, snapshot, correlation_id)
    polls = 0
    while not run.is_terminal:
        if polls >= max_polls:
            raise RuntimeError("character_lora: training did not finish in time")
        sleep_fn(_POLL_INTERVAL_S)
        run = adapter.poll(run)
        polls += 1
    if run.state != RUN_COMPLETED or not run.result_ref:
        raise RuntimeError(
            f"character_lora: training terminated without weights (state={run.state})"
        )
    return run


def run_character_lora_training(
    job_id: str, *, adapter: Any = None, sleep_fn: Any = None
) -> dict[str, Any]:
    """Train one character LoRA for ``Job(kind="character_lora")`` ``job_id``.

    Raises ``RuntimeError`` on any hard failure (no provider, too few references,
    empty output, rehost failure) so the Celery task's ``on_failure`` marks the
    job failed and refunds. Returns a small summary dict on success. ``adapter``
    is injectable for tests (defaults to the registered ``lora_train`` adapter).
    """
    job_id = (job_id or "").strip()
    if not job_id:
        raise RuntimeError("character_lora: run called without a job_id")

    ctx = _load_job_context(job_id)
    if ctx is None:
        raise RuntimeError(f"character_lora: job {job_id!r} not found")
    user_id, params = ctx
    correlation_id = str(params.get("_correlation_id") or "")

    character_id = str(params.get("character_id") or "").strip()
    if not character_id:
        raise RuntimeError("character_lora: job has no character_id")
    reference_keys = [str(k) for k in (params.get("reference_keys") or []) if str(k).strip()]
    if len(reference_keys) < _MIN_REFERENCES:
        raise RuntimeError("character_lora: at least one reference image is required")

    _set_progress(job_id, 10)
    reference_urls = _presign_reference_urls(reference_keys)
    if len(reference_urls) < _MIN_REFERENCES:
        raise RuntimeError("character_lora: could not presign reference images")

    adapter = adapter or _resolve_adapter()
    request = {
        "reference_urls": reference_urls,
        "steps": int(params.get("steps", 0) or 0),
        "rank": int(params.get("rank", 0) or 0),
        "base_model": str(params.get("base_model", "wan-2.2") or "wan-2.2"),
    }
    _set_progress(job_id, 30)
    run = drive_training(adapter, request, dict(params), correlation_id, sleep_fn=sleep_fn)

    _set_progress(job_id, 80)
    lora_key = _rehost_weights(character_id, run.result_ref)

    _persist_and_complete(
        job_id=job_id,
        user_id=user_id,
        character_id=character_id,
        lora_key=lora_key,
        meta={
            "correlation_id": correlation_id,
            "character_id": character_id,
            "provider_key": run.provider_key,
            "reference_count": len(reference_keys),
        },
    )
    logger.success(
        f"character_lora: completed job={job_id!r} -> {lora_key} "
        f"(character={character_id})"
    )
    return {"job_id": job_id, "character_id": character_id, "lora_key": lora_key}


def _rehost_weights(character_id: str, source_url: str) -> str:
    """Download the trained ``.safetensors`` and re-host it to OUR R2 bucket.

    The provider returns a signed/public URL; the trained weights are a
    user-owned PRIVATE object, so we copy them into our bucket under the
    character's LoRA prefix and only ever serve them via a fresh presign later.
    """
    from app.platform.storage.r2 import get_r2_client

    key = f"characters/{character_id}/lora/{uuid.uuid4().hex}.safetensors"
    data = _download(source_url)
    if not data:
        raise RuntimeError("character_lora: trained weights download was empty")
    get_r2_client().upload_bytes(key, data, content_type=_LORA_CONTENT_TYPE)
    return key


def _download(url: str) -> bytes:
    """Fetch remote bytes (httpx). Raises ``RuntimeError`` on any failure."""
    try:
        import httpx

        resp = httpx.get(url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:  # noqa: BLE001 - normalized to a hard training failure
        raise RuntimeError(f"character_lora: weights fetch failed: {exc}") from exc


def _persist_and_complete(
    *,
    job_id: str,
    user_id: str,
    character_id: str,
    lora_key: str,
    meta: dict[str, Any],
) -> None:
    """Write the LoRA key onto the character + mark the job complete atomically."""
    from app.domains.characters.repository import CharacterRepository
    from app.models.db.base import get_session
    from app.models.db.repositories import AssetRepository, JobRepository

    with get_session() as session:
        # Auto-inject the trained LoRA into every future shot of this character.
        CharacterRepository(session).set_lora_ref(character_id, lora_key)
        AssetRepository(session).create(
            user_id=user_id,
            kind="character_lora",
            r2_key=lora_key,
            job_id=job_id,
            content_type=_LORA_CONTENT_TYPE,
            meta=meta,
        )
        # ``result_key`` = the LoRA key so the existing GET /jobs/{id} poll +
        # presign-download flow serves the trained weights for free.
        JobRepository(session).mark_complete(job_id, lora_key)


def refund_character_lora_training(job_id: str) -> None:
    """Idempotently refund a failed training's credit debit (best-effort).

    Reads ``credits_cost`` / ``workspace_id`` from the job's params and grants
    the credits back to their source pool, setting ``refunded`` so a retry /
    duplicate failure hook cannot double-refund. Never raises.
    """
    job_id = (job_id or "").strip()
    if not job_id:
        return
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import CreditRepository, JobRepository

        with get_session() as session:
            job = JobRepository(session)._locked_job(job_id)
            if job is None:
                return
            params = dict(job.params or {})
            if params.get("refunded"):
                return  # already refunded — idempotent
            cost = int(params.get("credits_cost") or 0)
            if cost <= 0:
                return  # nothing was charged
            workspace_id = params.get("workspace_id") or None
            user_id = job.user_id

            credits = CreditRepository(session)
            if workspace_id:
                credits.workspace_grant(
                    workspace_id, cost, "character_lora_refund", user_id
                )
            else:
                credits.grant(user_id, cost, "character_lora_refund")

            job.params = {**params, "refunded": True}
            session.flush()
        logger.info(f"character_lora: refunded {cost} credit(s) for failed job={job_id!r}")
    except Exception as exc:  # noqa: BLE001 - refund is best-effort
        logger.error(f"character_lora: refund failed for job={job_id!r}: {exc}")


def _set_progress(job_id: str, progress: int) -> None:
    """Best-effort coarse progress update; never crashes the training."""
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            JobRepository(session).set_progress(job_id, progress)
    except Exception as exc:  # noqa: BLE001 - progress is cosmetic
        logger.debug(f"character_lora: progress update failed for {job_id!r}: {exc}")
