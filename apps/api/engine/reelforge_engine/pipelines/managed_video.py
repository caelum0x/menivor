"""Typed adapter around the migrated managed-video engine facade."""

from __future__ import annotations

from pathlib import Path

from reelforge_engine.contracts import GenerationRequest, GenerationResult
from reelforge_engine.runtime import runtime_profile


class ManagedVideoPipeline:
    name = "managed-video"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        # Importing the historical facade is deferred to the GPU worker call;
        # importing contracts or the API application never loads model stacks.
        # This is intentionally evaluated inside the GPU queue only. The
        # profile is the auditable bridge to acceleration/pipeline/diffusion/
        # model layers; clients see only the approved product capability.
        runtime_profile(self.name)
        from services.api_services.video_client import VideoClient

        ratio = (
            "9:16"
            if request.height > request.width
            else "16:9"
            if request.width > request.height
            else "1:1"
        )
        output = VideoClient().generate_video(
            request.prompt,
            str(request.reference_image_path) if request.reference_image_path else None,
            str(request.output_path),
            request.model,
            request.duration_seconds,
            video_ratio=ratio,
            seed=request.seed,
            **dict(request.parameters),
        )
        if not output:
            raise RuntimeError("managed-video pipeline returned no output path")
        return GenerationResult(
            output_path=Path(output),
            duration_seconds=float(request.duration_seconds),
            provider_run_id=request.correlation_id,
            model=request.model,
            correlation_id=request.correlation_id,
        )
