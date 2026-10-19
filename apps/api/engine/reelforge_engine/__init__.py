"""Stable private interface consumed by ReelForge generation workers."""

from reelforge_engine.contracts import GenerationMode, GenerationRequest, GenerationResult
from reelforge_engine.registry import GenerationPipeline, get_pipeline, register_pipeline
from reelforge_engine.runtime import EngineRuntimeProfile, runtime_profile

# Registration is explicit and product-owned; importing this package never
# scans the filesystem or loads model weights.
from reelforge_engine.pipelines.managed_video import ManagedVideoPipeline

register_pipeline(ManagedVideoPipeline())

__all__ = [
    "GenerationMode",
    "GenerationPipeline",
    "GenerationRequest",
    "GenerationResult",
    "EngineRuntimeProfile",
    "get_pipeline",
    "register_pipeline",
    "runtime_profile",
]
