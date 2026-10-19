"""GPU-worker runtime profile for the private generation engine.

The engine tree contains model implementations, diffusion helpers, pipelines,
and acceleration primitives.  They are not client SDK features.  This module is
the one narrow runtime declaration that product adapters use before invoking a
pipeline, preventing accidental API-process imports or dynamic model loading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class EngineRuntimeProfile:
    pipeline: str
    layers: Mapping[str, str]


MANAGED_VIDEO_PROFILE = EngineRuntimeProfile(
    pipeline="managed-video",
    layers={
        "acceleration": "GPU-only distributed/checkpoint primitives",
        "pipelines": "approved product orchestration",
        "k_diffusion": "GPU-only sampling adapters",
        "models": "licensed model and VAE implementations",
    },
)


def runtime_profile(name: str) -> EngineRuntimeProfile:
    if name != MANAGED_VIDEO_PROFILE.pipeline:
        raise KeyError(f"unknown ReelForge engine runtime profile: {name!r}")
    # These imports resolve only after ``configure_engine_imports`` in the GPU
    # worker. They avoid loading model weights while making every engine layer
    # part of the audited product execution profile.
    from acceleration.product_runtime import product_acceleration_policy
    from k_diffusion.product_runtime import product_sampling_policy
    from models.product_runtime import product_model_policy
    from pipelines.product_runtime import product_pipeline_policy

    acceleration = product_acceleration_policy()
    pipeline = product_pipeline_policy()
    sampling = product_sampling_policy()
    model = product_model_policy()
    return EngineRuntimeProfile(
        pipeline=pipeline.name,
        layers={
            "acceleration": f"{acceleration.device}; checkpointing={acceleration.checkpointing}",
            "pipelines": f"queue={pipeline.queue}; accepts={','.join(pipeline.accepts)}",
            "k_diffusion": f"sampler={sampling.sampler}; client_selectable={sampling.client_selectable}",
            "models": f"loaded_by={model.weights_loaded_by}; client_selectable={model.client_selectable}",
        },
    )
