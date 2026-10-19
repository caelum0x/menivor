"""Allowlisted product pipeline registry; no dynamic module discovery."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from reelforge_engine.contracts import GenerationRequest, GenerationResult


@runtime_checkable
class GenerationPipeline(Protocol):
    name: str

    def generate(self, request: GenerationRequest) -> GenerationResult:
        ...


_PIPELINES: dict[str, GenerationPipeline] = {}


def register_pipeline(pipeline: GenerationPipeline) -> None:
    name = pipeline.name.strip()
    if not name:
        raise ValueError("generation pipeline must have a name")
    _PIPELINES[name] = pipeline


def get_pipeline(name: str) -> GenerationPipeline:
    try:
        return _PIPELINES[name]
    except KeyError as exc:
        raise KeyError(
            f"generation pipeline {name!r} is not product-registered; "
            f"available={sorted(_PIPELINES)}"
        ) from exc
