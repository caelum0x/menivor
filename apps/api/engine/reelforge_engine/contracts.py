"""Dependency-light typed values crossing the product/engine boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


class GenerationMode(StrEnum):
    TEXT_TO_VIDEO = "t2v"
    IMAGE_TO_VIDEO = "i2v"


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    prompt: str
    mode: GenerationMode
    model: str
    output_path: Path
    width: int
    height: int
    duration_seconds: int
    correlation_id: str
    reference_image_path: Path | None = None
    seed: int | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("generation prompt must not be empty")
        if not self.model.strip():
            raise ValueError("generation model must not be empty")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("generation dimensions must be positive")
        if not 1 <= self.duration_seconds <= 30:
            raise ValueError("generation duration must be between 1 and 30 seconds")
        if self.mode is GenerationMode.IMAGE_TO_VIDEO and self.reference_image_path is None:
            raise ValueError("image-to-video requires a local reference image")


@dataclass(frozen=True, slots=True)
class GenerationResult:
    output_path: Path
    duration_seconds: float
    provider_run_id: str
    model: str
    correlation_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
