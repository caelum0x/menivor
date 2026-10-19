"""Sampling policy boundary for approved GPU video generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SamplingPolicy:
    sampler: str = "provider-managed"
    client_selectable: bool = False


def product_sampling_policy() -> SamplingPolicy:
    return SamplingPolicy()
