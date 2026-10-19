"""The preset shelf catalog (MH2): 12 filter presets and 12 model presets.

Filter presets index the existing FFmpeg camera moves (``domains/motion``) and
filter-class looks (``services/compose/vfx.py``); they render on standard
credits on our own lanes. Model presets are generative effects: an
image-to-video or text-to-video preset SKU (``routing/tiers.PRESET_SKUS``)
plus a prompt template, loaded from ``assets/presets/<id>@v<N>.json``; they
run on AI-video credits only.

Public fields (name, blurb) never name a vendor or a model: see
:func:`vendor_hits`. Pure data, no I/O beyond reading the checked-in files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

KIND_FILTER = "filter"
KIND_MODEL = "model"
CREDIT_STANDARD = "standard"
CREDIT_AI_VIDEO = "ai_video"

_API = Path(__file__).resolve().parents[3]
ASSETS = _API / "assets" / "presets"
DENYLIST = _API.parents[1] / "policy" / "copy-denylist.json"
_FILE = re.compile(r"^(?P<id>[a-z0-9-]+)@v(?P<version>\d+)\.json$")


@dataclass(frozen=True)
class Preset:
    id: str
    kind: str
    name: str
    blurb: str
    credit_kind: str
    version: int = 1
    # filter presets
    camera_motion: str = ""
    effects: tuple[str, ...] = ()
    intensity: int = 50
    # model presets
    preset_sku: str = ""
    tier: str = "draft"
    seconds: int = 5
    prompt_template: str = ""
    inputs: tuple[str, ...] = ("subject",)
    source_file: str = ""

    @property
    def needs_image(self) -> bool:
        return "image" in self.inputs


def _f(pid: str, name: str, blurb: str, camera: str, effects: tuple[str, ...] = (), intensity: int = 60) -> Preset:
    return Preset(id=pid, kind=KIND_FILTER, name=name, blurb=blurb, credit_kind=CREDIT_STANDARD,
                  camera_motion=camera, effects=effects, intensity=intensity)


FILTER_PRESETS: tuple[Preset, ...] = (
    _f("crash-zoom", "Crash zoom", "A fast punch toward your subject on the hook.", "crash_zoom_in", intensity=70),
    _f("dreamy-push", "Dreamy push-in", "A slow push-in with a soft glow.", "dolly_in", ("glow",)),
    _f("vintage-film", "Vintage film", "A drifting frame with film grain and warm tones.", "ken_burns_fx",
       ("film_burn",)),
    _f("whip-pan", "Whip pan", "A quick sideways whip between moments.", "whip_pan"),
    _f("orbit", "Orbit", "The frame circles your subject.", "orbit_360_fake"),
    _f("drone-rush", "Drone rush", "A fast flying shake, like a racing drone.", "fpv_drone_shake"),
    _f("handheld-vlog", "Handheld vlog", "A handheld feel with a light leak.", "handheld_shake", ("light_leak",)),
    _f("glitch-punch", "Glitch punch", "A zoom punch with a colour-split glitch.", "zoom_punch_in", ("glitch",)),
    _f("dutch-drama", "Dutch drama", "A tilted frame for tension.", "dutch_angle"),
    _f("crane-reveal", "Crane reveal", "The frame rises to reveal the scene.", "crane_up"),
    _f("speed-ramp", "Speed ramp", "Slow, then fast, then slow again.", "speed_ramp"),
    _f("rack-focus", "Rack focus", "Focus pulls from soft to sharp.", "rack_focus"),
)


def _load_model(path: Path) -> Preset:
    match = _FILE.match(path.name)
    if not match:
        raise ValueError(f"preset file {path.name} must be named <id>@v<N>.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("id") != match["id"] or int(data.get("version", 0)) != int(match["version"]):
        raise ValueError(f"{path.name}: id or version does not match the file name")
    return Preset(
        id=str(data["id"]), kind=KIND_MODEL, name=str(data["name"]), blurb=str(data["blurb"]),
        credit_kind=CREDIT_AI_VIDEO, version=int(data["version"]), preset_sku=str(data["preset_sku"]),
        tier=str(data.get("tier") or "draft"), seconds=int(data.get("seconds") or 5),
        prompt_template=str(data["prompt_template"]), inputs=tuple(data.get("inputs") or ("subject",)),
        source_file=str(path),
    )


@lru_cache(maxsize=1)
def model_presets() -> tuple[Preset, ...]:
    """The newest version of each model preset file, sorted by id."""
    newest: dict[str, Preset] = {}
    for path in sorted(ASSETS.glob("*@v*.json")):
        preset = _load_model(path)
        if preset.id not in newest or preset.version > newest[preset.id].version:
            newest[preset.id] = preset
    order = [p.stem.split("@")[0] for p in sorted(ASSETS.glob("*@v*.json"))]
    seen: list[str] = []
    for pid in order:
        if pid not in seen:
            seen.append(pid)
    return tuple(newest[pid] for pid in seen)


def filter_presets() -> tuple[Preset, ...]:
    return FILTER_PRESETS


def all_presets() -> tuple[Preset, ...]:
    return FILTER_PRESETS + model_presets()


def get(preset_id: str) -> Preset | None:
    wanted = str(preset_id or "").strip().lower()
    return next((p for p in all_presets() if p.id == wanted), None)


# --------------------------------------------------------------------------- #
# Copy guard: no vendor or model names in public preset copy
# --------------------------------------------------------------------------- #
_MODEL_NAMES = re.compile(
    r"\b(?:kling|veo ?\d|sora|runway|seedance|hailuo|minimax|luma|pika|pixverse|midjourney|"
    r"stable diffusion|sdxl|flux(?:\.1| pro| dev| schnell)|wan ?2(?:\.\d)?|hunyuan|mochi|ltx-?video|"
    r"cogvideox?|claude|llama|whisper|replicate|fal\.ai|comfyui|"
    r"nano ?banana|gpt-?image|dall-?e|imagen|seedream|gemini)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _vendor_patterns() -> tuple[re.Pattern[str], ...]:
    try:
        data = json.loads(DENYLIST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return tuple(
        re.compile(r["match"]["value"], re.IGNORECASE)
        for r in data.get("rules", [])
        if r.get("category") == "vendor" and "menivor" in r.get("products", [])
        and (r.get("match") or {}).get("type") == "regex"
    )


def vendor_hits(text: str) -> list[str]:
    unit = " ".join(str(text or "").split())
    hits = [m.group(0) for pattern in _vendor_patterns() for m in pattern.finditer(unit)]
    return hits + [m.group(0) for m in _MODEL_NAMES.finditer(unit)]


__all__ = [
    "CREDIT_AI_VIDEO", "CREDIT_STANDARD", "FILTER_PRESETS", "KIND_FILTER", "KIND_MODEL", "Preset",
    "all_presets", "filter_presets", "get", "model_presets", "vendor_hits",
]
