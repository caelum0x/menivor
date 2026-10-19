"""SHARED Wave-1 motion/camera contract — pure, frozen dataclasses + helpers.

This module is the single source of truth for the camera-control data shape that
BOTH the motion compiler (path B dispatch) and the Wan camera provider adapter
build against. It is intentionally dependency-free (no DB, no network, no routing
imports) so the provider adapter can ``from app.domains.motion.spec import
CameraControlSpec, to_wan_request`` without pulling in the HTTP/DB layers.

Three frozen dataclasses:

* :class:`FilterPlan`   — path A: a pure-FFmpeg camera move (+ optional VFX mix),
  fed straight into ``services/compose/vfx.build_vfx_node``.
* :class:`CameraControlSpec` — path B: a Wan camera-control request description
  (named pose or a raw ``pose_trajectory``), turned into a provider payload by
  :func:`to_wan_request`.
* :class:`MotionPlan`   — the compiled result the render worker branches on via
  ``motion_class`` in {"filter", "model", "hybrid"}.

Frame-count rule: Wan's VAE has ``temporal_compression_ratio=4`` so a clip length
MUST satisfy ``k*4 + 1``. :func:`snap_length` snaps any seconds→frames request to
the nearest legal value so callers never send an illegal length.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# License classes — Wan is open-weights (paid-safe for resale).
# --------------------------------------------------------------------------- #
LICENSE_CLASS_OPEN_WEIGHTS = "open_weights"
PAID_SAFE_LICENSES = frozenset({"open_weights", "apache-2.0"})

# The nine named Wan camera moves (everything else uses a raw ``pose_trajectory``).
WAN_CAMERA_POSES = frozenset(
    {
        "Static", "Pan Up", "Pan Down", "Pan Left", "Pan Right",
        "Zoom In", "Zoom Out", "Anti Clockwise", "ClockWise",
    }
)

# Wan VAE temporal compression: a legal clip length is ``k*4 + 1`` frames.
_TEMPORAL_COMPRESSION_RATIO = 4
_MIN_LENGTH = 5  # smallest legal k*4+1 (k=1)


@dataclass(frozen=True)
class FilterPlan:
    """Path A — a deterministic pure-FFmpeg camera move (+ optional VFX mix)."""

    camera_motion: str            # an id vfx._camera_fragment() recognizes (existing or alias)
    intensity: int = 50           # 0..100, passed straight to vfx.build_vfx_node
    effects: tuple[str, ...] = ()  # optional VFX-mix ids


@dataclass(frozen=True)
class CameraControlSpec:
    """Path B — the model-class Wan camera-control contract (provider-imported)."""

    preset_id: str
    capability: str               # "image_to_video" | "text_to_video"
    camera_pose: str              # a WAN_CAMERA_POSES member or "Custom"
    prompt_fragment: str          # natural-language camera phrase
    speed: float = 1.0            # 0..10; ~1.0 == Wan base motion scale
    width: int = 832              # step-16
    height: int = 480             # step-16 (portrait flips to 480x832 at request time)
    length: int = 81              # MUST satisfy k*4+1
    fx: float = 0.5
    fy: float = 0.5
    cx: float = 0.5
    cy: float = 0.5
    pose_trajectory: tuple[tuple[float, ...], ...] = ()  # raw c2w rows for "Custom"
    provider_hints: tuple[str, ...] = ("wan_camera",)    # provider_keys, priority order
    param_map: tuple[tuple[str, str], ...] = ()          # sorted native overrides (hashable)
    license_class: str = LICENSE_CLASS_OPEN_WEIGHTS
    intensity: int = 50


@dataclass(frozen=True)
class MotionPlan:
    """The compiled plan — the render worker branches on ``motion_class``."""

    preset_id: str
    motion_class: str             # "filter" | "model" | "hybrid"
    filter: FilterPlan | None = None       # present for filter + hybrid (fallback)
    model: CameraControlSpec | None = None  # present for model + hybrid


def snap_length(seconds: float, fps: int = 16) -> int:
    """Snap ``seconds*fps`` to the nearest legal Wan clip length (``k*4 + 1``, >=5).

    Pure + total: any non-negative ``seconds`` maps to a valid frame count so a
    caller can never send an illegal length to the provider.
    """
    raw_frames = max(0.0, float(seconds)) * max(1, int(fps))
    k = round((raw_frames - 1) / _TEMPORAL_COMPRESSION_RATIO)
    length = k * _TEMPORAL_COMPRESSION_RATIO + 1
    return max(_MIN_LENGTH, length)


def to_wan_request(
    spec: CameraControlSpec,
    *,
    start_image_url: str = "",
    prompt: str,
    negative_prompt: str = "",
    aspect_ratio: str = "9:16",
) -> dict:
    """Build the provider-agnostic Wan camera-control request from a spec.

    The returned dict is exactly the payload the ``wan_camera`` adapter POSTs; the
    ``camera`` sub-dict feeds the ``WanCameraEmbedding`` node and the top-level
    fields feed the Fun-Control sampler. ``estimated_seconds`` is an fps-agnostic
    duration estimate used by the wallet ``quote()`` (the motion domain never
    debits — that stays in the reels/wallet layer).
    """
    return {
        "capability": spec.capability,
        "prompt": f"{prompt}. {spec.prompt_fragment}".strip(". "),
        "negative_prompt": negative_prompt,
        "start_image_url": start_image_url,
        "aspect_ratio": aspect_ratio,
        "num_frames": spec.length,
        "estimated_seconds": max(1, round(spec.length / 16)),
        "camera": {
            "camera_pose": spec.camera_pose,
            "speed": spec.speed,
            "width": spec.width,
            "height": spec.height,
            "length": spec.length,
            "fx": spec.fx,
            "fy": spec.fy,
            "cx": spec.cx,
            "cy": spec.cy,
            "pose_trajectory": [list(r) for r in spec.pose_trajectory],
            **{k: v for k, v in spec.param_map},
        },
    }
