"""Kernel registry (Python parity of ``src/registry.ts``).

Maps a kernel id → (category, callable). Lookup + list-by-category so the API,
web and mobile all resolve the same kernel set.
"""

from __future__ import annotations

from typing import Callable

from . import kernels

CAMERA = "camera"
VFX = "vfx"

_REGISTRY: dict[str, tuple[str, Callable[..., dict]]] = {
    "push-in": (CAMERA, kernels.push_in),
    "ken-burns": (CAMERA, kernels.ken_burns),
    "handheld": (CAMERA, kernels.handheld),
    "rgb-split": (VFX, kernels.rgb_split),
    "film-grain": (VFX, kernels.film_grain),
    "shake": (VFX, kernels.shake),
}


def get_kernel(kernel_id: str) -> Callable[..., dict] | None:
    entry = _REGISTRY.get(kernel_id)
    return entry[1] if entry else None


def category_of(kernel_id: str) -> str | None:
    entry = _REGISTRY.get(kernel_id)
    return entry[0] if entry else None


def list_kernels(category: str | None = None) -> list[str]:
    ids = [k for k, (cat, _) in _REGISTRY.items() if category is None or cat == category]
    return sorted(ids)


def apply(kernel_id: str, t: float, **params) -> dict:
    fn = get_kernel(kernel_id)
    if fn is None:
        raise KeyError(f"unknown kernel {kernel_id!r}")
    return fn(t, **params)
