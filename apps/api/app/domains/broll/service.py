"""Standalone AI B-roll generation as an async ``Job(kind="broll_gen")``.

The synchronous ``broll.suggest_broll(source="ai")`` path is fine for a fast
first cut, but a single ComfyUI/Wan clip is 30-120s of GPU — well past the
gateway/proxy timeout of a blocking HTTP request. So a *studio* generation runs
as its own Celery job on the ``render`` queue, exactly like the avatar stage:

    POST /generation/broll/generate -> Job(kind="broll_gen") -> generate_broll_clip_task
                                                             │
                                    run_broll_generation ────┘  (this module)
                                    provider.generate_clip -> R2 -> Asset -> done

This module is the **service delegate** the Celery task calls (mirroring how the
stage tasks delegate to ``reelforge.stage_*``), so the task stays a thin wrapper
and the real work is unit-testable without a broker.

Two entry points:

* :func:`run_broll_generation` — load the job's stored params, generate the clip,
  re-host it to R2 under ``jobs/<job_id>/broll/<uuid>.mp4``, persist an ``Asset``
  row with provenance, and mark the job complete (``result_key`` = the clip key).
  Raises on failure so the task's ``on_failure`` records the root cause + refunds.
* :func:`refund_broll_generation` — idempotently return the debited credits when a
  generation fails (called from the task's terminal-failure hook).

Params persisted on the ``Job`` row (all optional except ``prompt``)::

    {"prompt", "mode"("t2v"|"i2v"), "image_key"?, "width", "height",
     "duration_s", "seed"?, "workflow_id"?,
     "credits_cost", "workspace_id"?, "refunded"?}

``credits_cost`` / ``workspace_id`` are written by the controller at debit time so
the failure path can refund the correct pool without re-deriving pricing.

**Catalog-model shots (Very ___ Time template lane).** Three more OPTIONAL keys
route a shot through the media gateway's provider executor instead of the B-roll
provider::

    "video_model": "bytedance/seedance-2.0-i2v",          # a video catalog id
    "references": [{"key": "<R2 key>", "role": "first_frame" | "identity" | "style"}],
    "brief": {"format", "action", "camera", "continuity", "audio", "constraints"}

When ``video_model`` is set: reference keys (or ``image_key`` alone, as the first
frame, when ``references`` is absent) are presigned from our own bucket, the
prompt is the structured brief when ``brief`` is present (else ``prompt``), the
model runs as a house-paid call (the parent already paid: no wallet debit), the
output is polled to completion and re-hosted exactly like the provider path.
Keys are written server-side by the template lane; raw URLs are refused here.
Without ``video_model`` nothing changes.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

_BROLL_ASSET_KIND: str = "broll"
_BROLL_CONTENT_TYPE: str = "video/mp4"
_DEFAULT_CLIP_SECONDS: float = 5.0

# Presign TTL for an i2v reference image handed to the (remote) GPU worker. The
# image is our OWN R2 object (ownership validated at the controller) exposed via
# a short-lived signed GET — never an arbitrary client URL (SSRF guard, §8).
_IMAGE_PRESIGN_TTL_S: int = 900


def _load_job_context(job_id: str) -> tuple[str, dict[str, Any]] | None:
    """Return ``(user_id, params)`` for a job, or ``None`` if it is gone."""
    from app.models.db.base import get_session
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        job = JobRepository(session).get(job_id)
        if job is None:
            return None
        return job.user_id, dict(job.params or {})


def _resolve_image_url(mode: str, image_key: str) -> str | None:
    """Presign the OWNED R2 image for i2v, or ``None`` for t2v / on any failure.

    ``image_key`` was ownership-checked by the controller (the authorization
    boundary) before the job was created, so here we only mint a short-lived
    signed GET URL against our OWN bucket — never an arbitrary client URL, so the
    worker fetch stays inside the SSRF allow-list (§8).
    """
    if mode != "i2v" or not image_key:
        return None
    try:
        from app.platform.storage.r2 import get_r2_client

        return get_r2_client().presign_get(image_key, expires=_IMAGE_PRESIGN_TTL_S)
    except Exception as exc:  # noqa: BLE001 - presign failure: skip i2v image
        logger.warning(f"broll_gen: could not presign i2v image {image_key!r}: {exc}")
        return None


def run_broll_generation(job_id: str) -> dict[str, Any]:
    """Generate one AI B-roll clip for ``Job(kind="broll_gen")`` ``job_id``.

    Raises ``RuntimeError`` on any hard failure (provider disabled, empty output,
    upload failure) so the Celery task's ``on_failure`` marks the job failed and
    refunds the debit. Returns a small summary dict on success.
    """
    job_id = (job_id or "").strip()
    if not job_id:
        raise RuntimeError("broll_gen: run called without a job_id")

    ctx = _load_job_context(job_id)
    if ctx is None:
        raise RuntimeError(f"broll_gen: job {job_id!r} not found")
    user_id, params = ctx
    correlation_id = str(params.get("_correlation_id") or "")
    logger.info(
        f"broll_gen: executing job={job_id!r}, correlation_id={correlation_id or 'n/a'}"
    )

    if str(params.get("video_model") or "").strip():
        return _run_catalog_model(job_id, user_id, params, correlation_id)

    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("broll_gen: job has no prompt")

    mode = str(params.get("mode") or "t2v").strip() or "t2v"
    _set_progress(job_id, 10)

    from app.domains.broll import get_broll_provider

    provider = get_broll_provider()
    if not provider.is_enabled():
        raise RuntimeError("broll_gen: provider is not configured")

    image_url = _resolve_image_url(mode, str(params.get("image_key") or ""))
    if mode == "i2v" and not image_url:
        raise RuntimeError("broll_gen: i2v generation requires a usable image")

    _set_progress(job_id, 30)
    clip = provider.generate_clip(
        prompt,
        mode=mode,
        image_url=image_url,
        width=int(params.get("width") or 1080),
        height=int(params.get("height") or 1920),
        duration_s=float(params.get("duration_s") or _DEFAULT_CLIP_SECONDS),
        seed=params.get("seed"),
        workflow_id=params.get("workflow_id") or None,
        correlation_id=correlation_id,
    )
    if not clip or not clip.get("clip_path"):
        raise RuntimeError("broll_gen: generation produced no clip")

    _set_progress(job_id, 80)
    broll_key = _rehost_clip(job_id, clip["clip_path"])
    _cleanup_temp(clip.get("clip_path"))

    duration = float(clip.get("duration") or params.get("duration_s") or 0.0)
    _persist_and_complete(
        job_id=job_id,
        user_id=user_id,
        broll_key=broll_key,
        duration=duration,
        meta={
            "correlation_id": correlation_id,
            "prompt": prompt,
            "mode": mode,
            "seed": params.get("seed"),
            "workflow_id": params.get("workflow_id"),
            # Immutable comfy-workflow-schema pin the provider dispatched against
            # (empty when the provider does not pin, e.g. a managed-API backend).
            "workflow_slug": clip.get("workflow_slug", ""),
            "workflow_pin": clip.get("workflow_pin", ""),
            "provider_job_id": clip.get("provider_job_id", ""),
        },
    )
    logger.success(
        f"broll_gen: completed job={job_id!r} -> {broll_key} ({duration:.1f}s), "
        f"correlation_id={correlation_id or 'n/a'}"
    )
    return {"job_id": job_id, "broll_key": broll_key, "duration": duration}


def _rehost_clip(job_id: str, local_path: str) -> str:
    """Upload the provider's temp clip to this job's R2 B-roll prefix."""
    from app.services.broll import _upload_broll_clip

    return _upload_broll_clip(job_id, local_path)


def _persist_and_complete(
    *,
    job_id: str,
    user_id: str,
    broll_key: str,
    duration: float,
    meta: dict[str, Any],
) -> None:
    """Persist the ``Asset`` provenance row and mark the job complete atomically."""
    from app.models.db.base import get_session
    from app.models.db.repositories import AssetRepository, JobRepository

    with get_session() as session:
        AssetRepository(session).create(
            user_id=user_id,
            kind=_BROLL_ASSET_KIND,
            r2_key=broll_key,
            job_id=job_id,
            content_type=_BROLL_CONTENT_TYPE,
            duration_s=duration,
            meta=meta,
        )
        # ``result_key`` = the clip key, so the existing ``GET /jobs/{id}`` poll +
        # presign-download flow serves a completed broll_gen job for free.
        JobRepository(session).mark_complete(job_id, broll_key)


def refund_broll_generation(job_id: str) -> None:
    """Idempotently refund a failed generation's credit debit (best-effort).

    Reads ``credits_cost`` / ``workspace_id`` from the job's stored params and
    grants the credits back to the pool they were debited from, setting a
    ``refunded`` flag so a retry/duplicate failure hook cannot double-refund.
    Never raises — a reconciliation failure must not crash the worker.
    """
    job_id = (job_id or "").strip()
    if not job_id:
        return
    # AI-video credits held by the generation go back (idempotent, never raises).
    from app.services.billing.premium_credits import refund_job_once

    refund_job_once(job_id)
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
                credits.workspace_grant(workspace_id, cost, "broll_gen_refund", user_id)
            else:
                credits.grant(user_id, cost, "broll_gen_refund")

            job.params = {**params, "refunded": True}
            session.flush()
        logger.info(f"broll_gen: refunded {cost} credit(s) for failed job={job_id!r}")
    except Exception as exc:  # noqa: BLE001 - refund is best-effort
        logger.error(f"broll_gen: refund failed for job={job_id!r}: {exc}")


def _set_progress(job_id: str, progress: int) -> None:
    """Best-effort coarse progress update; never crashes the generation."""
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            JobRepository(session).set_progress(job_id, progress)
    except Exception as exc:  # noqa: BLE001 - progress is cosmetic
        logger.debug(f"broll_gen: progress update failed for {job_id!r}: {exc}")


def _cleanup_temp(local_path: str | None) -> None:
    """Remove the provider's temp clip after re-hosting, best-effort."""
    try:
        import os

        if local_path and os.path.exists(local_path):
            os.remove(local_path)
    except Exception:  # noqa: BLE001 - cleanup is best-effort
        pass


# --------------------------------------------------------------------------- #
# Catalog-model shots (``video_model``): the media gateway's provider executor
# --------------------------------------------------------------------------- #
_CATALOG_POLL_S: float = 10.0
_CATALOG_TIMEOUT_S: float = 25 * 60.0
_DOWNLOAD_TIMEOUT_S: float = 120.0


def _executor() -> Any:
    from app.domains.gateway.provider_execution import MediaProviderExecutor

    return MediaProviderExecutor()


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def _download_to_temp(url: str) -> str:
    """Stream the provider output to a temp ``.mp4`` and return its path."""
    import tempfile

    import requests

    fd, path = tempfile.mkstemp(prefix="broll-", suffix=".mp4")
    with requests.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT_S) as resp, open(fd, "wb") as fh:
        resp.raise_for_status()
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if chunk:
                fh.write(chunk)
    return path


def _presign_key(key: str) -> str:
    from app.platform.storage.r2 import get_r2_client

    return get_r2_client().presign_get(key, expires=_IMAGE_PRESIGN_TTL_S)


def _shot_references(params: dict[str, Any]) -> tuple[Any, ...]:
    """The job's references as storage-key :class:`Reference` items (``image_key`` fallback)."""
    from app.domains.gateway.video_brief import BriefError, Reference, parse_references

    raw = params.get("references")
    if not raw and params.get("image_key"):
        raw = [{"key": params.get("image_key"), "role": "first_frame"}]
    if raw is not None and not isinstance(raw, list):
        raise RuntimeError("broll_gen: references must be a list")
    try:
        refs = parse_references(raw or [])
    except BriefError as exc:
        raise RuntimeError(f"broll_gen: {exc}") from exc
    if any(not r.is_key for r in refs):
        raise RuntimeError("broll_gen: references must be storage keys, not URLs")
    return tuple(Reference(url=r.url, role=r.role) for r in refs)


def _fit_seconds(model: Any, wanted: float) -> int:
    """The nearest clip length the model renders (fal tables), within its maximum."""
    seconds = max(1, int(round(float(wanted or _DEFAULT_CLIP_SECONDS))))
    if model.max_seconds:
        seconds = min(seconds, int(model.max_seconds))
    if model.provider == "kling-fal":
        from app.domains.gateway.fal_duration import spec_for

        spec = spec_for(model.model_ref)
        if spec is not None and spec.allowed and seconds not in spec.allowed:
            seconds = min(spec.allowed, key=lambda s: (abs(s - seconds), s))
    return seconds


def _aspect_ratio(params: dict[str, Any]) -> str:
    width, height = int(params.get("width") or 1080), int(params.get("height") or 1920)
    return "9:16" if height > width else ("16:9" if width > height else "1:1")


def _catalog_prompt(params: dict[str, Any], refs: tuple[Any, ...]) -> str:
    from app.domains.gateway.video_brief import BriefError, brief_from_mapping

    brief = params.get("brief")
    if brief:
        try:
            return brief_from_mapping(brief, refs)
        except BriefError as exc:
            raise RuntimeError(f"broll_gen: {exc}") from exc
    return str(params.get("prompt") or "").strip()


def _run_until_terminal(executor: Any, request: Any) -> Any:
    result = executor.submit(request)
    waited = 0.0
    while result.handle.state not in ("COMPLETED", "FAILED", "CANCELLED"):
        if waited >= _CATALOG_TIMEOUT_S:
            raise RuntimeError(f"broll_gen: the video model did not finish within {int(_CATALOG_TIMEOUT_S)}s")
        _sleep(_CATALOG_POLL_S)
        waited += _CATALOG_POLL_S
        result = executor.poll(result.handle)
    if result.handle.state != "COMPLETED" or not result.outputs:
        message = result.error.message if result.error else "the video model failed"
        raise RuntimeError(f"broll_gen: {message}")
    return result


def _run_catalog_model(job_id: str, user_id: str, params: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    """Run one shot on a catalog video model (house-paid: the parent job already paid)."""
    from app.domains.gateway.media_catalog import VIDEO, get_model
    from app.domains.gateway.media_gateway import GatewayError, _provider_request, reference_inputs
    from app.domains.gateway.video_brief import Reference
    from app.domains.routing.license_class import LicenseError, assert_model_sellable

    model_id = str(params.get("video_model") or "").strip()
    model = get_model(model_id)
    if model is None or model.modality != VIDEO:
        raise RuntimeError(f"broll_gen: {model_id!r} is not a video model in the catalog")
    try:
        assert_model_sellable(model.id)
    except LicenseError as exc:
        raise RuntimeError(f"broll_gen: {exc}") from exc

    key_refs = _shot_references(params)
    prompt = _catalog_prompt(params, key_refs)
    if not prompt and not key_refs:
        raise RuntimeError("broll_gen: job has no prompt, brief or image")
    _set_progress(job_id, 10)
    url_refs = tuple(Reference(url=_presign_key(r.url), role=r.role) for r in key_refs)
    try:
        image_url, input_refs = reference_inputs(model, url_refs)
    except GatewayError as exc:
        raise RuntimeError(f"broll_gen: {exc}") from exc

    seconds = _fit_seconds(model, float(params.get("duration_s") or _DEFAULT_CLIP_SECONDS))
    request = _provider_request(
        model,
        correlation_id=correlation_id or f"broll:{job_id}",
        prompt=prompt,
        cost_micros=seconds * model.price_micros,
        duration_seconds=seconds,
        aspect_ratio=_aspect_ratio(params),
        image_url=image_url,
        input_refs=input_refs,
        generate_audio=params.get("generate_audio") if isinstance(params.get("generate_audio"), bool) else None,
    )
    _set_progress(job_id, 30)
    result = _run_until_terminal(_executor(), request)

    _set_progress(job_id, 80)
    local_path = _download_to_temp(result.outputs[0].reference)
    try:
        broll_key = _rehost_clip(job_id, local_path)
    finally:
        _cleanup_temp(local_path)
    _persist_and_complete(
        job_id=job_id,
        user_id=user_id,
        broll_key=broll_key,
        duration=float(seconds),
        meta={
            "correlation_id": correlation_id,
            "prompt": prompt,
            "mode": "catalog",
            "video_model": model.id,
            "provider": model.provider,
            "provider_job_id": result.handle.run_id,
            "reference_roles": [r.role for r in key_refs],
            "house_cost_micros": seconds * model.price_micros,
            "seed": params.get("seed"),
        },
    )
    logger.success(f"broll_gen: completed job={job_id!r} on {model.id} -> {broll_key} ({seconds}s)")
    return {"job_id": job_id, "broll_key": broll_key, "duration": float(seconds), "video_model": model.id}
