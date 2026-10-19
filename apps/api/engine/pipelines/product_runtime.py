"""Product-safe pipeline declaration, separate from experimental pipelines."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PipelinePolicy:
    name: str = "managed-video"
    queue: str = "generation"
    accepts: tuple[str, ...] = ("t2v", "i2v")


def product_pipeline_policy() -> PipelinePolicy:
    return PipelinePolicy()
