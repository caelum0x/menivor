"""Model-layer policy for the private ReelForge engine facade."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    weights_loaded_by: str = "gpu_worker"
    client_selectable: bool = False


def product_model_policy() -> ModelPolicy:
    return ModelPolicy()
