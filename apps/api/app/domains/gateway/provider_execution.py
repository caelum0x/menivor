"""Public provider execution boundary shared by Menivor API and Prism.

The concrete provider SDK/HTTP adapters live behind this module.  Callers pass
the versioned, persistence-neutral contract from ``provider-adapter-kit`` and
receive the same normalized handle/result regardless of which application is
orchestrating the request.  Wallets, database rows, routing and authentication
remain outside this boundary.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from reelforge_provider_adapter.execution import (
    ProviderCostV1,
    ProviderExecutionErrorV1,
    ProviderExecutionException,
    ProviderHandleV1,
    ProviderOutputV1,
    ProviderRequestV1,
    ProviderResultV1,
)

from app.domains.routing.providers.kling_fal import KlingError, KlingFalAdapter


# Compatibility name for the API and Prism integration.  The actual exception
# contract is owned and versioned by provider-adapter-kit.
ProviderExecutionFailure = ProviderExecutionException


def _estimated_cost(handle: ProviderHandleV1) -> int:
    value = handle.opaque.get("estimated_cost_micros", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderExecutionFailure(
            ProviderExecutionErrorV1(
                phase="poll",
                category="provider",
                retryable=False,
                acceptance="accepted",
                message="persisted provider handle has invalid cost metadata",
            )
        )
    return value


def _cost_for_success(handle: ProviderHandleV1) -> ProviderCostV1:
    return ProviderCostV1(
        success=True,
        cost_micros=_estimated_cost(handle),
        source=str(handle.opaque.get("cost_source", "catalog_estimate")),
        unit=str(handle.opaque.get("unit", "")),
        quantity_units=int(handle.opaque.get("quantity_units", 0) or 0),
        price_version=str(handle.opaque.get("price_version", "")),
    )


def _output_kind(modality: str) -> str:
    return modality if modality in {"image", "video", "audio"} else "file"


def _normalized_error(exc: Exception, *, phase: str) -> ProviderExecutionErrorV1:
    kind = str(getattr(exc, "kind", "provider") or "provider")
    category = {
        "auth": "auth",
        "validation": "validation",
        "rate_limit": "rate_limit",
        "capacity": "capacity",
        "transient": "transport",
        "transport": "transport",
        "not_found": "not_found",
        "policy": "policy",
    }.get(kind, "provider")
    retryable = bool(getattr(exc, "retryable", False))
    raw_acceptance = str(getattr(exc, "acceptance", "") or "")
    if raw_acceptance in {"not_accepted", "definitely_not_accepted"}:
        acceptance = "not_accepted"
    elif raw_acceptance in {"accepted", "unknown"}:
        acceptance = raw_acceptance
    elif phase == "submit" and category in {"auth", "validation", "rate_limit", "capacity"}:
        acceptance = "not_accepted"
    else:
        acceptance = "accepted" if phase != "submit" else "unknown"
    provider_code = str(getattr(exc, "status", "") or "")
    return ProviderExecutionErrorV1(
        phase=phase,
        category=category,
        retryable=retryable,
        acceptance=acceptance,
        message=str(exc) or type(exc).__name__,
        provider_code=provider_code,
    )


def _kokoro_base_url() -> str:
    from app.domains.routing.providers.kokoro import kokoro_url

    return kokoro_url()


def _kokoro_voice_clip(base_url: str, *, text: str, voice_id: str, speed: Any):
    """Synthesize via the Kokoro-FastAPI sidecar and host the audio (R2)."""
    from app.domains.routing.providers.kokoro import KokoroClient
    from app.domains.routing.providers.voice_gen import VoiceClip, host_audio_bytes

    result = KokoroClient(base_url).synthesize(
        text, voice=voice_id or "af_heart", speed=speed
    )
    return VoiceClip(
        run_id="",
        output_url=host_audio_bytes(
            result.audio, result.content_type, key_prefix="prism/voice/kokoro"
        ),
        characters=result.characters,
        raw={"voice": result.voice},
    )


def _raise_normalized(exc: Exception, *, phase: str) -> None:
    if isinstance(exc, ProviderExecutionFailure):
        raise exc
    raise ProviderExecutionFailure(_normalized_error(exc, phase=phase)) from exc


class MediaProviderExecutor:
    """Concrete image/video/audio provider executor with a stable public ABI."""

    def __init__(self, *, api_key: str = "", session_http: Any = None) -> None:
        self._api_key = api_key
        self._session = session_http

    @property
    def provider_key(self) -> str:
        # One executor dispatches the provider encoded in each versioned request.
        return "media"

    def submit(self, request: ProviderRequestV1) -> ProviderResultV1:
        try:
            if request.modality == "image":
                return self._submit_image(request)
            if request.modality == "video":
                return self._submit_video(request)
            if request.modality == "audio":
                return self._submit_audio(request)
            raise KlingError(
                f"unsupported media modality {request.modality!r}",
                kind="validation",
            )
        except Exception as exc:  # provider errors share the KlingError taxonomy
            _raise_normalized(exc, phase="submit")

    def poll(self, handle: ProviderHandleV1) -> ProviderResultV1:
        if handle.state in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise ProviderExecutionFailure(
                ProviderExecutionErrorV1(
                    phase="poll",
                    category="validation",
                    retryable=False,
                    acceptance="accepted",
                    message="terminal provider handles must not be polled",
                )
            )
        try:
            return self._poll(handle)
        except Exception as exc:
            _raise_normalized(exc, phase="poll")

    def cancel(self, handle: ProviderHandleV1) -> ProviderResultV1:
        """Best-effort provider-side cancellation, then a CANCELLED terminal.

        Calls the upstream cancel API for providers that expose one (kling-fal,
        runway, luma, wan, ark). Providers whose upstream API has no cancellation
        primitive (veo/minimax/suno/heygen) are abandoned locally: no provider call is
        made, tracking stops, and the handle is driven to the CANCELLED terminal
        state. Either way the returned handle is terminal and never charges the
        caller (the poll path only meters COMPLETED work).
        """
        if handle.state in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise ProviderExecutionFailure(
                ProviderExecutionErrorV1(
                    phase="cancel",
                    category="validation",
                    retryable=False,
                    acceptance="accepted",
                    message="terminal provider handles cannot be cancelled",
                )
            )
        try:
            self._cancel(handle)
        except Exception as exc:
            _raise_normalized(exc, phase="cancel")
        return self._terminal_result(
            handle, state="CANCELLED", failure="cancelled by caller"
        )

    def _cancel(self, handle: ProviderHandleV1) -> bool:
        provider = handle.provider_key
        if provider == "kling-fal":
            from app.domains.routing.providers.kling_fal import KlingJob

            cancel_url = str(handle.opaque.get("cancel_url") or "")
            if not cancel_url and handle.response_url:
                # fal's queue cancel action is the request resource + /cancel.
                cancel_url = f"{handle.response_url}/cancel"
            job = KlingJob(
                request_id=handle.run_id,
                status_url=handle.status_url,
                response_url=handle.response_url,
                cancel_url=cancel_url,
            )
            return KlingFalAdapter(
                api_key=self._api_key or os.getenv("FAL_KEY", ""),
                model=handle.model_ref,
                session=self._session,
            ).cancel(job)
        if provider == "runway":
            from app.domains.routing.providers.runway_gen import RunwayAdapter, RunwayTask

            return RunwayAdapter(
                api_key=self._api_key or os.getenv("RUNWAY_API_SECRET", ""),
                model=handle.model_ref,
                session=self._session,
            ).cancel(RunwayTask(task_id=handle.run_id))
        if provider == "luma":
            from app.domains.routing.providers.luma_gen import LumaAdapter, LumaGeneration

            return LumaAdapter(
                api_key=self._api_key or os.getenv("LUMAAI_API_KEY", ""),
                model=handle.model_ref,
                session=self._session,
            ).cancel(LumaGeneration(generation_id=handle.run_id))
        if provider == "wan":
            from app.domains.routing.providers.wan_replicate import WanAdapter, WanPrediction

            return WanAdapter(
                api_key=self._api_key or os.getenv("REPLICATE_API_TOKEN", ""),
                model=handle.model_ref,
                session=self._session,
            ).cancel(
                WanPrediction(
                    prediction_id=handle.run_id, get_url=handle.response_url
                )
            )
        if provider == "ark":
            from app.domains.routing.providers.seedance_ark import ArkTask, SeedanceArkAdapter

            return SeedanceArkAdapter(
                api_key=self._api_key or os.getenv("ARK_API_KEY", ""),
                model=handle.model_ref,
                session=self._session,
            ).cancel(ArkTask(task_id=handle.run_id))
        if provider in {"veo", "minimax", "suno", "heygen"}:
            # These upstream APIs expose no cancellation primitive; the honest
            # behavior is a local abandon — stop tracking and drive to CANCELLED.
            # (Voice — elevenlabs/tts — is synchronous, so its handles are already
            # terminal and never reach cancellation.)
            return False
        raise KlingError(f"provider {provider!r} is not wired", kind="validation")

    @staticmethod
    def _handle(
        request: ProviderRequestV1,
        run_id: str,
        *,
        state: str = "IN_QUEUE",
        status_url: str = "",
        response_url: str = "",
        extra: dict[str, Any] | None = None,
    ) -> ProviderHandleV1:
        parameters = request.parameters
        cost = parameters.get("estimated_cost_micros", 0)
        if isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
            raise KlingError("estimated_cost_micros must be a non-negative integer", kind="validation")
        quantity = parameters.get("quantity_units", 0)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise KlingError("quantity_units must be a non-negative integer", kind="validation")
        opaque: dict[str, Any] = {
            "modality": request.modality,
            "estimated_cost_micros": cost,
            "cost_source": str(parameters.get("cost_source", "catalog_estimate")),
            "unit": str(parameters.get("unit", "")),
            "quantity_units": quantity,
            "price_version": str(parameters.get("price_version", "")),
        }
        if extra:
            opaque.update(extra)
        return ProviderHandleV1(
            provider_key=request.provider_key,
            model_ref=request.model_ref,
            run_id=run_id,
            state=state,
            status_url=status_url,
            response_url=response_url,
            opaque=opaque,
        )

    def _submit_image(self, request: ProviderRequestV1) -> ProviderResultV1:
        provider = request.provider_key
        if request.input_refs and provider not in ("fal-image", "replicate-image"):
            # Never drop reference images silently: only the fal and Replicate image lanes send them.
            raise KlingError(f"provider {provider!r} does not take reference images", kind="validation")
        if provider == "fal-image":
            from app.domains.gateway._fal_image import fal_generate_image

            output = fal_generate_image(
                request.model_ref,
                request.prompt,
                api_key=self._api_key or os.getenv("FAL_KEY", ""),
                image_urls=tuple(request.input_refs),
                session=self._session,
            )
        elif provider == "openai-image":
            from app.domains.gateway.openai_image import openai_generate_image

            output = openai_generate_image(
                request.model_ref,
                request.prompt,
                api_key=self._api_key or os.getenv("OPENAI_API_KEY", ""),
                session=self._session,
            )
        elif provider == "replicate-image":
            from app.domains.gateway.replicate_image import replicate_generate_image

            output = replicate_generate_image(
                request.model_ref,
                request.prompt,
                api_key=self._api_key or os.getenv("REPLICATE_API_TOKEN", ""),
                image_urls=tuple(request.input_refs),
                session=self._session,
            )
        elif provider == "imagen":
            from app.domains.gateway.imagen_image import imagen_generate_image

            output = imagen_generate_image(
                request.model_ref,
                request.prompt,
                api_key=self._api_key or os.getenv("GEMINI_API_KEY", ""),
                session=self._session,
            )
        else:
            raise KlingError(f"provider {provider!r} is not wired", kind="validation")

        run_hash = hashlib.sha256(
            f"{request.provider_key}\0{request.model_ref}\0{request.correlation_id}".encode()
        ).hexdigest()[:32]
        handle = self._handle(request, f"sync-{run_hash}", state="COMPLETED")
        return ProviderResultV1(
            handle=handle,
            outputs=(ProviderOutputV1(reference=output, kind="image"),),
            cost=_cost_for_success(handle),
        )

    def _submit_video(self, request: ProviderRequestV1) -> ProviderResultV1:
        image_url = request.input_refs[0] if request.input_refs else ""
        # "reference": every input ref is a role-tagged reference (r2v rows);
        # otherwise the first input ref is the first frame.
        reference_mode = request.parameters.get("image_mode") == "reference"
        provider = request.provider_key
        if provider == "kling-fal":
            from app.domains.gateway.fal_duration import DurationUnsupported, duration_extra

            try:
                # Per-model wire form (Veo "8s", Hailuo "6"/"10", ...), refused
                # before any request leaves for fal (H4).
                extra = duration_extra(request.model_ref, request.duration_seconds)
            except DurationUnsupported as exc:
                raise KlingError(str(exc), kind="validation") from exc
            job = KlingFalAdapter(
                api_key=self._api_key or os.getenv("FAL_KEY", ""),
                model=request.model_ref,
                session=self._session,
            ).submit(
                prompt=request.prompt,
                seconds=request.duration_seconds,
                aspect_ratio=request.aspect_ratio,
                image_url="" if reference_mode else image_url,
                image_urls=request.input_refs if reference_mode else (),
                extra=extra or None,
            )
            handle = self._handle(
                request,
                job.request_id,
                status_url=job.status_url,
                response_url=job.response_url,
                extra={"cancel_url": job.cancel_url} if job.cancel_url else None,
            )
        elif provider == "ark":
            from app.domains.routing.providers.seedance_ark import (
                ROLE_FIRST_FRAME,
                ROLE_REFERENCE,
                SeedanceArkAdapter,
            )

            ark_task = SeedanceArkAdapter(
                api_key=self._api_key or os.getenv("ARK_API_KEY", ""),
                model=request.model_ref,
                session=self._session,
            ).submit(
                prompt=request.prompt,
                image_urls=request.input_refs,
                mode=ROLE_REFERENCE if reference_mode else ROLE_FIRST_FRAME,
                seconds=request.duration_seconds,
                aspect_ratio=request.aspect_ratio,
                resolution=str(request.parameters.get("resolution", "") or "720p"),
            )
            handle = self._handle(request, ark_task.task_id)
        elif provider == "runway":
            from app.domains.routing.providers.runway_gen import RunwayAdapter

            task = RunwayAdapter(
                api_key=self._api_key or os.getenv("RUNWAY_API_SECRET", ""),
                model=request.model_ref,
                session=self._session,
            ).submit(
                prompt=request.prompt,
                image_url=image_url,
                seconds=request.duration_seconds,
                ratio="768:1280" if request.aspect_ratio == "9:16" else "1280:768",
            )
            handle = self._handle(request, task.task_id)
        elif provider == "veo":
            from app.domains.routing.providers.veo_gen import VeoAdapter

            operation = VeoAdapter(
                api_key=self._api_key or os.getenv("GEMINI_API_KEY", ""),
                model=request.model_ref,
                session=self._session,
            ).submit(
                prompt=request.prompt,
                seconds=request.duration_seconds,
                aspect_ratio=request.aspect_ratio,
                image_url=image_url,
            )
            handle = self._handle(request, operation.name)
        elif provider == "luma":
            from app.domains.routing.providers.luma_gen import LumaAdapter

            generation = LumaAdapter(
                api_key=self._api_key or os.getenv("LUMAAI_API_KEY", ""),
                model=request.model_ref,
                session=self._session,
            ).submit(
                prompt=request.prompt,
                seconds=request.duration_seconds,
                aspect_ratio=request.aspect_ratio,
                image_url=image_url,
            )
            handle = self._handle(request, generation.generation_id)
        elif provider == "minimax":
            from app.domains.routing.providers.minimax_gen import MinimaxAdapter

            task = MinimaxAdapter(
                api_key=self._api_key or os.getenv("MINIMAX_API_KEY", ""),
                model=request.model_ref,
                session=self._session,
            ).submit(
                prompt=request.prompt,
                seconds=request.duration_seconds,
                image_url=image_url,
            )
            handle = self._handle(request, task.task_id)
        elif provider == "wan":
            from app.domains.routing.providers.wan_replicate import WanAdapter

            prediction = WanAdapter(
                api_key=self._api_key or os.getenv("REPLICATE_API_TOKEN", ""),
                model=request.model_ref,
                session=self._session,
            ).submit(
                prompt=request.prompt,
                seconds=request.duration_seconds,
                aspect_ratio=request.aspect_ratio,
                image_url="" if reference_mode else image_url,
                image_urls=request.input_refs if reference_mode else (),
                resolution=str(request.parameters.get("resolution", "") or ""),
                generate_audio=request.parameters.get("generate_audio"),
            )
            handle = self._handle(
                request,
                prediction.prediction_id,
                response_url=prediction.get_url,
            )
        elif provider == "heygen":
            # Avatar (talking-head) is served under the video modality — async.
            from app.domains.routing.providers.avatar_gen import HeyGenAvatarAdapter

            task = HeyGenAvatarAdapter(
                api_key=self._api_key or os.getenv("HEYGEN_API_KEY", ""),
                model=request.model_ref,
                session=self._session,
            ).submit(
                prompt=request.prompt,
                voice_id=str(request.parameters.get("voice_id", "") or ""),
                image_url=image_url,
                seconds=request.duration_seconds,
            )
            handle = self._handle(request, task.task_id)
        else:
            raise KlingError(f"provider {provider!r} is not wired", kind="validation")
        return ProviderResultV1(handle=handle, cost=ProviderCostV1.not_chargeable())

    def _submit_audio(self, request: ProviderRequestV1) -> ProviderResultV1:
        provider = request.provider_key
        if provider == "suno":
            from app.domains.routing.providers.suno_gen import SunoAdapter

            task = SunoAdapter(
                api_key=self._api_key or os.getenv("SUNO_API_KEY", ""),
                model=request.model_ref,
                session=self._session,
            ).submit(
                prompt=request.prompt,
                instrumental=bool(request.parameters.get("instrumental", False)),
            )
            handle = self._handle(request, task.task_id)
            return ProviderResultV1(handle=handle, cost=ProviderCostV1.not_chargeable())
        if provider in {"elevenlabs", "tts"}:
            # Voice (TTS) is served under the audio modality — synchronous.
            return self._submit_voice(request)
        raise KlingError(
            f"provider {provider!r} is not wired for audio",
            kind="validation",
        )

    def _submit_voice(self, request: ProviderRequestV1) -> ProviderResultV1:
        """Synchronous TTS: synthesize, host the audio, return a COMPLETED result.

        ElevenLabs and the self-hosted TTS backends return audio immediately, so
        (like image generation) the submit call terminalizes. Byte-returning
        providers are hosted to a real ``https`` output_url by the adapter — the
        inline ``data:`` form is reserved for images by the execution contract, so
        voice must yield a hosted URL exactly as Suno returns its ``audioUrl``.
        """
        params = request.parameters
        voice_id = str(params.get("voice_id", "") or "")
        provider = request.provider_key
        if provider == "elevenlabs":
            from app.domains.routing.providers.voice_gen import ElevenLabsVoiceAdapter

            clip = ElevenLabsVoiceAdapter(
                api_key=self._api_key or os.getenv("ELEVENLABS_API_KEY", ""),
                model=request.model_ref,
                session=self._session,
            ).submit(prompt=request.prompt, voice_id=voice_id)
        elif request.model_ref == "kokoro" and _kokoro_base_url():
            # tts/kokoro -> the Kokoro-FastAPI sidecar (KOKORO_URL), which speaks the
            # OpenAI-compatible /v1/audio/speech protocol, not the generic /tts shape.
            clip = _kokoro_voice_clip(
                _kokoro_base_url(),
                text=request.prompt,
                voice_id=voice_id,
                speed=params.get("speed", 1.0),
            )
        else:  # self-hosted / free TTS fallbacks (provider_key == "tts")
            from app.domains.routing.providers.voice_gen import SelfHostVoiceAdapter

            clip = SelfHostVoiceAdapter(
                provider_key=provider,
                model=request.model_ref,
                api_key=self._api_key,
                session=self._session,
            ).submit(
                prompt=request.prompt,
                voice_id=voice_id,
                language=str(params.get("language", "") or ""),
            )
        run_hash = hashlib.sha256(
            f"{request.provider_key}\0{request.model_ref}\0{request.correlation_id}".encode()
        ).hexdigest()[:32]
        handle = self._handle(
            request, clip.run_id or f"sync-{run_hash}", state="COMPLETED"
        )
        return ProviderResultV1(
            handle=handle,
            outputs=(ProviderOutputV1(reference=clip.output_url, kind="audio"),),
            cost=_cost_for_success(handle),
        )

    @staticmethod
    def _terminal_result(
        handle: ProviderHandleV1,
        *,
        state: str,
        output_url: str = "",
        failure: str = "",
    ) -> ProviderResultV1:
        current = handle.with_state(state)
        if state == "COMPLETED":
            return ProviderResultV1(
                handle=current,
                outputs=(
                    ProviderOutputV1(
                        reference=output_url,
                        kind=_output_kind(str(handle.opaque.get("modality", "file"))),
                    ),
                ),
                cost=_cost_for_success(current),
            )
        if state in {"FAILED", "CANCELLED"}:
            return ProviderResultV1(
                handle=current,
                cost=ProviderCostV1.not_chargeable(),
                error=ProviderExecutionErrorV1(
                    phase="poll",
                    category="provider",
                    retryable=False,
                    acceptance="accepted",
                    message=failure or "provider generation failed",
                ),
            )
        return ProviderResultV1(handle=current, cost=ProviderCostV1.not_chargeable())

    def _poll(self, handle: ProviderHandleV1) -> ProviderResultV1:
        provider = handle.provider_key
        if provider == "kling-fal":
            from app.domains.routing.providers.kling_fal import KlingJob

            job = KlingJob(
                request_id=handle.run_id,
                status_url=handle.status_url,
                response_url=handle.response_url,
            )
            KlingFalAdapter(
                api_key=self._api_key or os.getenv("FAL_KEY", ""),
                model=handle.model_ref,
                session=self._session,
            ).poll(job)
            state = (
                "COMPLETED"
                if job.video_url
                else (
                    job.state
                    if job.state in {"FAILED", "CANCELLED"}
                    else job.state
                )
            )
            return self._terminal_result(
                handle,
                state=state,
                output_url=job.video_url,
                failure=job.failure,
            )
        if provider == "ark":
            from app.domains.routing.providers.seedance_ark import ArkTask, SeedanceArkAdapter

            ark_task = ArkTask(task_id=handle.run_id)
            SeedanceArkAdapter(
                api_key=self._api_key or os.getenv("ARK_API_KEY", ""),
                model=handle.model_ref,
                session=self._session,
            ).poll(ark_task)
            state = {
                "succeeded": "COMPLETED",
                "failed": "FAILED",
                "expired": "FAILED",
                "cancelled": "CANCELLED",
                "queued": "IN_QUEUE",
            }.get(ark_task.status, "IN_PROGRESS")
            return self._terminal_result(
                handle, state=state, output_url=ark_task.output_url, failure=ark_task.failure
            )
        if provider == "runway":
            from app.domains.routing.providers.runway_gen import RunwayAdapter, RunwayTask

            task = RunwayTask(task_id=handle.run_id)
            RunwayAdapter(
                api_key=self._api_key or os.getenv("RUNWAY_API_SECRET", ""),
                model=handle.model_ref,
                session=self._session,
            ).poll(task)
            state = {"SUCCEEDED": "COMPLETED", "FAILED": "FAILED", "PENDING": "IN_QUEUE"}.get(
                task.state, "IN_PROGRESS"
            )
            return self._terminal_result(
                handle, state=state, output_url=task.output_url, failure=task.failure
            )
        if provider == "veo":
            from app.domains.routing.providers.veo_gen import VeoAdapter, VeoOperation

            operation = VeoOperation(name=handle.run_id)
            VeoAdapter(
                api_key=self._api_key or os.getenv("GEMINI_API_KEY", ""),
                model=handle.model_ref,
                session=self._session,
            ).poll(operation)
            state = "FAILED" if operation.done and operation.error else (
                "COMPLETED" if operation.done else "IN_PROGRESS"
            )
            return self._terminal_result(
                handle,
                state=state,
                output_url=operation.output_url,
                failure=operation.error,
            )
        if provider == "luma":
            from app.domains.routing.providers.luma_gen import LumaAdapter, LumaGeneration

            generation = LumaGeneration(generation_id=handle.run_id)
            LumaAdapter(
                api_key=self._api_key or os.getenv("LUMAAI_API_KEY", ""),
                model=handle.model_ref,
                session=self._session,
            ).poll(generation)
            state = {"completed": "COMPLETED", "failed": "FAILED", "queued": "IN_QUEUE"}.get(
                generation.state, "IN_PROGRESS"
            )
            return self._terminal_result(
                handle,
                state=state,
                output_url=generation.output_url,
                failure=generation.failure,
            )
        if provider == "minimax":
            from app.domains.routing.providers.minimax_gen import MinimaxAdapter, MinimaxTask

            task = MinimaxTask(task_id=handle.run_id)
            MinimaxAdapter(
                api_key=self._api_key or os.getenv("MINIMAX_API_KEY", ""),
                model=handle.model_ref,
                session=self._session,
            ).poll(task)
            state = {"Success": "COMPLETED", "Fail": "FAILED", "Queueing": "IN_QUEUE"}.get(
                task.status, "IN_PROGRESS"
            )
            return self._terminal_result(
                handle, state=state, output_url=task.output_url, failure=task.failure
            )
        if provider == "wan":
            from app.domains.routing.providers.wan_replicate import WanAdapter, WanPrediction

            prediction = WanPrediction(
                prediction_id=handle.run_id,
                get_url=handle.response_url,
            )
            WanAdapter(
                api_key=self._api_key or os.getenv("REPLICATE_API_TOKEN", ""),
                model=handle.model_ref,
                session=self._session,
            ).poll(prediction)
            state = {
                "succeeded": "COMPLETED",
                "failed": "FAILED",
                "canceled": "CANCELLED",
                "starting": "IN_QUEUE",
            }.get(prediction.status, "IN_PROGRESS")
            return self._terminal_result(
                handle,
                state=state,
                output_url=prediction.output_url,
                failure=prediction.failure,
            )
        if provider == "suno":
            from app.domains.routing.providers.suno_gen import SunoAdapter, SunoTask

            task = SunoTask(task_id=handle.run_id)
            SunoAdapter(
                api_key=self._api_key or os.getenv("SUNO_API_KEY", ""),
                model=handle.model_ref,
                session=self._session,
            ).poll(task)
            state = "COMPLETED" if task.output_url else ("FAILED" if task.failure else "IN_PROGRESS")
            return self._terminal_result(
                handle, state=state, output_url=task.output_url, failure=task.failure
            )
        if provider == "heygen":
            from app.domains.routing.providers.avatar_gen import (
                HeyGenAvatarAdapter,
                HeyGenTask,
            )

            task = HeyGenTask(task_id=handle.run_id)
            HeyGenAvatarAdapter(
                api_key=self._api_key or os.getenv("HEYGEN_API_KEY", ""),
                model=handle.model_ref,
                session=self._session,
            ).poll(task)
            state = "COMPLETED" if task.output_url else ("FAILED" if task.failure else "IN_PROGRESS")
            return self._terminal_result(
                handle, state=state, output_url=task.output_url, failure=task.failure
            )
        raise KlingError(f"provider {provider!r} is not wired", kind="validation")


__all__ = ["MediaProviderExecutor", "ProviderExecutionFailure"]
