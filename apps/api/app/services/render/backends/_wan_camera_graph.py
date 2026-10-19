"""PURE (no I/O) Wan2.2-Fun camera-control workflow builder.

The UI-editor → API-format conversion is done ONCE, offline, into the pinned
asset ``assets/workflows/wan22_fun_control_camera.api.json``. This module only
LOADS that asset and injects per-request values into a deep COPY (the codebase's
immutability rule — the cached template is never mutated).

Injection map (from a ``to_wan_request`` dict):

* uploaded image ``{name}`` (+subfolder) → ``node100.inputs.image``
* ``prompt`` → ``node121.inputs.prompt`` ; ``negative_prompt`` → ``node122.inputs.prompt``
* ``camera.camera_pose`` → ``node131.inputs.camera_pose1`` (pose2..4 = "Static")
* ``camera.speed`` → ``node131.inputs.speed``
* clip length → ``node131.inputs.video_length`` AND ``node135.inputs.video_length``
* ``camera.{fx,fy,cx,cy}`` → ``node130.inputs.{fx,fy,cx,cy}``
* ``base_resolution`` (from spec width/height) → ``node135.inputs.base_resolution``
* optional ``seed/steps/cfg`` → ``node135.inputs.{seed,steps,cfg}`` when supplied

Four gotcha guards live here:

1. **Pose-name translation** — ``"Anti Clockwise" → "ACW"`` and
   ``"ClockWise" → "CW"`` BEFORE injecting (the CameraCombine node's dropdown uses
   the short names; the long names 400 in ``validate_prompt``).
2. **Legal-length enforcement** — snap to ``k*4 + 1`` and keep it identical across
   ``node131`` and ``node135`` (the Wan VAE temporal ratio is 4).
3. **base_resolution snap** — snap the spec width/height to the nearest of the
   supported buckets ``{512, 640, 768, 896, 960, 1024}``.
4. **Absent optionals** — never inject empty strings for the sampler's optional
   ``validation_video/control_video/end_image/ref_image`` inputs; they are omitted
   from the pinned asset so ComfyUI does not misread ``""`` as a node reference.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

# The pinned API-format graph lives beside the other workflow assets.
TEMPLATE_PATH = Path(__file__).resolve().parents[4] / "assets" / "workflows" / (
    "wan22_fun_control_camera.api.json"
)

# Gotcha 1: CameraCombine dropdown values differ from the routing-layer pose names.
POSE_TRANSLATIONS: dict[str, str] = {
    "Anti Clockwise": "ACW",
    "ClockWise": "CW",
}

# Gotcha 2: Wan VAE temporal_compression_ratio == 4 → legal length is k*4 + 1.
_TEMPORAL_RATIO = 4
_MIN_LENGTH = 5

# Gotcha 3: the supported base_resolution buckets.
BASE_RESOLUTIONS: tuple[int, ...] = (512, 640, 768, 896, 960, 1024)

# Node ids in the pinned graph.
NODE_IMAGE = "100"
NODE_PROMPT = "121"
NODE_NEG_PROMPT = "122"
NODE_CAMERA_COMBINE = "131"
NODE_CAMERA_TRAJECTORY = "130"
NODE_SAMPLER = "135"
OUTPUT_NODE = "106"

# Tolerant output list keys (mirrors wan_camera.py's _OUTPUT_LIST_KEYS).
_OUTPUT_LIST_KEYS: tuple[str, ...] = ("gifs", "videos", "images", "files")

_TEMPLATE_CACHE: dict | None = None


def load_template() -> dict:
    """Read + cache the pinned API-format graph (never mutated by callers)."""
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        with open(TEMPLATE_PATH, encoding="utf-8") as fp:
            _TEMPLATE_CACHE = json.load(fp)
    return _TEMPLATE_CACHE


def translate_pose(pose: str) -> str:
    """Map a routing-layer pose name to the CameraCombine dropdown value."""
    return POSE_TRANSLATIONS.get(str(pose or "").strip(), str(pose or "").strip() or "Static")


def snap_length(frames: int) -> int:
    """Snap a frame count to the nearest legal Wan clip length (``k*4 + 1``, >=5)."""
    try:
        raw = int(frames)
    except (TypeError, ValueError):
        raw = _MIN_LENGTH
    k = round((raw - 1) / _TEMPORAL_RATIO)
    length = k * _TEMPORAL_RATIO + 1
    return max(_MIN_LENGTH, length)


def snap_base_resolution(width: int, height: int) -> int:
    """Snap a spec width/height to the nearest supported base_resolution bucket.

    Uses the mean of width and height (the Wan pipeline works a single-scalar
    working resolution), then picks the nearest supported bucket.
    """
    try:
        target = (int(width) + int(height)) / 2.0
    except (TypeError, ValueError):
        target = 640.0
    return min(BASE_RESOLUTIONS, key=lambda r: (abs(r - target), r))


def build_graph(req: dict, image_ref: dict | None = None) -> dict:
    """Deep-copy the pinned template and inject the per-request values.

    ``req`` is a ``to_wan_request`` dict; ``image_ref`` is the ``{name, subfolder}``
    returned by ``ComfyUIClient.upload_image`` (or ``None`` for a text-only run).
    Returns a NEW graph — the cached template is never mutated.
    """
    graph = copy.deepcopy(load_template())
    camera = req.get("camera") if isinstance(req.get("camera"), dict) else {}

    # -- image ------------------------------------------------------------- #
    if image_ref:
        name = str(image_ref.get("name") or "")
        subfolder = str(image_ref.get("subfolder") or "")
        if name:
            graph[NODE_IMAGE]["inputs"]["image"] = f"{subfolder}/{name}" if subfolder else name

    # -- prompts ----------------------------------------------------------- #
    if req.get("prompt") is not None:
        graph[NODE_PROMPT]["inputs"]["prompt"] = str(req.get("prompt") or "")
    if req.get("negative_prompt") is not None:
        graph[NODE_NEG_PROMPT]["inputs"]["prompt"] = str(req.get("negative_prompt") or "")

    # -- camera pose (guard 1) + speed ------------------------------------- #
    pose = translate_pose(camera.get("camera_pose", "Static"))
    combine = graph[NODE_CAMERA_COMBINE]["inputs"]
    combine["camera_pose1"] = pose
    combine["camera_pose2"] = "Static"
    combine["camera_pose3"] = "Static"
    combine["camera_pose4"] = "Static"
    if camera.get("speed") is not None:
        combine["speed"] = camera.get("speed")

    # -- length (guard 2: identical across 131 + 135) ---------------------- #
    length = snap_length(camera.get("length") or req.get("num_frames") or 81)
    combine["video_length"] = length
    graph[NODE_SAMPLER]["inputs"]["video_length"] = length

    # -- intrinsics -------------------------------------------------------- #
    trajectory = graph[NODE_CAMERA_TRAJECTORY]["inputs"]
    for key in ("fx", "fy", "cx", "cy"):
        if camera.get(key) is not None:
            trajectory[key] = camera.get(key)

    # -- sampler resolution (guard 3) + optional overrides ----------------- #
    sampler = graph[NODE_SAMPLER]["inputs"]
    sampler["base_resolution"] = snap_base_resolution(
        camera.get("width", 640), camera.get("height", 640)
    )
    for key in ("seed", "steps", "cfg"):
        value = req.get(key)
        if value is None:
            value = camera.get(key)
        if value is not None:
            sampler[key] = value

    # Guard 4: optional sampler inputs stay absent (never injected as "").
    return graph


def resolve_output(history_outputs: dict) -> dict | None:
    """Walk ``outputs[106]`` tolerant of gifs/videos/images and return the first ref.

    Returns ``{filename, subfolder, type}`` for ``/view`` URL building, or ``None``
    when no saved file is present yet.
    """
    if not isinstance(history_outputs, dict):
        return None
    node_out = history_outputs.get(OUTPUT_NODE)
    if not isinstance(node_out, dict):
        # Some shapes flatten a single node's outputs to the top level.
        node_out = history_outputs
    for key in _OUTPUT_LIST_KEYS:
        items = node_out.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("filename"):
                    return {
                        "filename": str(item.get("filename")),
                        "subfolder": str(item.get("subfolder") or ""),
                        "type": str(item.get("type") or "output"),
                    }
    return None
