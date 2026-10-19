"""Product allowlist gate for the bounded lipsync (speak) selectors.

Clients pick a bounded speak *product preset* (a reviewed lipsync provider key),
never an arbitrary ComfyUI deployment or model id (mirrors
``domains/broll/workflows.py``). :func:`require_approved_provider` rejects any
selector outside the reviewed allowlist before any GPU spend;
:func:`product_engine_capability` exposes the bounded selectors + their license
classes so the UI can render only the choices a client may actually invoke.

Pure metadata + a boundary guard — the allowlist is the union of the seeded open
lipsync configs (MuseTalk, LatentSync) intersected with an optional deployment
allowlist. No network, no DB.
"""

from __future__ import annotations

from typing import Any

from app.models.exception import HttpException


def approved_provider_keys() -> frozenset[str]:
    """The reviewed lipsync provider keys a client may select.

    Sourced from the seeded :data:`LIPSYNC_CONFIGS` (the one place the open
    lipsync providers are defined), so adding a config makes it selectable
    without editing this gate.
    """
    from app.domains.routing.providers._lipsync import LIPSYNC_CONFIGS

    return frozenset(LIPSYNC_CONFIGS)


def require_approved_provider(provider_key: str, request_id: str) -> None:
    """Reject a lipsync ``provider_key`` outside the reviewed allowlist (400).

    An empty selector is allowed — the domain resolves a default deterministically
    via ``speak.selection.choose_lipsync_provider``.
    """
    provider_key = (provider_key or "").strip()
    if not provider_key:
        return
    if provider_key.lower() not in approved_provider_keys():
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: lipsync provider is not approved for this deployment"
            ),
        )


def product_engine_capability() -> dict[str, Any]:
    """Expose the bounded lipsync engine capability clients may actually invoke.

    Web, mobile, and desktop get a stable speak product selector (a reviewed
    lipsync provider + its license class), not arbitrary ComfyUI graphs, model
    weights, or schedulers — the GPU worker owns those internal choices.
    """
    from app.domains.routing.providers._lipsync import LIPSYNC_CONFIGS
    from app.domains.speak.licensing import license_class_for

    providers = []
    for key in sorted(LIPSYNC_CONFIGS):
        cfg = LIPSYNC_CONFIGS[key]
        lic = license_class_for(key)
        providers.append(
            {
                "provider": key,
                "capability": cfg.capability,
                "metering_unit": cfg.metering_unit,
                "license_class": (lic.value if lic else cfg.license_class),
                "latency_band": cfg.latency_band,
            }
        )
    return {
        "speak": {
            "modes": ["image_audio_to_video"],
            "providers": providers,
            "runtime": "gpu_worker",
        }
    }
