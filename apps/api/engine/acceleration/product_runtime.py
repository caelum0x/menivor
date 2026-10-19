"""Lightweight acceleration policy exposed to the private product engine.

This module intentionally imports neither torch nor distributed backends. The
actual sharding/checkpoint implementations remain lazy beneath the GPU worker.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccelerationPolicy:
    device: str = "cuda"
    checkpointing: bool = True
    distributed: bool = False


def product_acceleration_policy() -> AccelerationPolicy:
    return AccelerationPolicy()
