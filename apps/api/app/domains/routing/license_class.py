"""License-class + deprecation helpers for license-clean, sunset-aware routing.

Two route-time (and deploy-time) safety rails from the P8 plan:

1. **License class** — some model weights are non-commercial (NC) or research-only
   (Wav2Lip, XTTS, F5-TTS, some Hunyuan checkpoints). A paying customer's render
   must never touch NC weights. :func:`is_route_allowed` hard-excludes them for
   paid usage; the same table backs the deploy-time ``license-gate``.

2. **Deprecation / sunset** — models get sunset (e.g. the Sora 2 API removal). A
   model past (or near) its sunset date must not be selected for new jobs;
   :func:`is_sunset` / :func:`sunset_status` drive migration onboarding onto a
   routed replacement.

Pure data + predicates, deterministic (dates are passed in) — the routing policy
and the deploy gate share this one source of truth.

MO1 (2026-09-29) makes the paid gate fail closed for public model ids:
:func:`is_model_sellable` resolves a ``vendor/model`` id to a licence row and
answers ``False`` for non-commercial, research-only, unreviewed or unrecorded
weights. The media gateway, the catalog's live promotion and the paid presenter
stage call it. ``docs/THIRD_PARTY_MODELS.md`` is the human-readable register and
a test keeps it in sync with this table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# License classes, most-permissive → most-restricted.
PERMISSIVE = "permissive"      # Apache/MIT/commercial API — always OK
COMMERCIAL_API = "commercial_api"  # hosted API with commercial terms — OK
RESTRICTED = "restricted"      # commercial-with-conditions — OK, may need attribution
NON_COMMERCIAL = "non_commercial"  # NC weights — BLOCK for paying users
RESEARCH_ONLY = "research_only"    # research license — BLOCK for any monetized use
UNREVIEWED = "unreviewed"          # weights licence not yet recorded with a source — BLOCK for paid

_BLOCK_FOR_PAID = frozenset({NON_COMMERCIAL, RESEARCH_ONLY, UNREVIEWED})
ALL_CLASSES = frozenset({PERMISSIVE, COMMERCIAL_API, RESTRICTED, NON_COMMERCIAL, RESEARCH_ONLY, UNREVIEWED})


@dataclass(frozen=True)
class ModelLicense:
    """A model's license class + optional sunset date (ISO) + replacement."""

    model_key: str
    license_class: str
    sunset_on: date | None = None
    replacement: str = ""
    note: str = ""


# Seed table (extend as adapters land). NC/research flags mirror the plan's
# hard-exclude list; sunset dates drive migration onboarding.
_LICENSES: dict[str, ModelLicense] = {
    # Hosted commercial APIs — safe for paid.
    "kling": ModelLicense("kling", COMMERCIAL_API),
    "higgsfield": ModelLicense(
        "higgsfield", COMMERCIAL_API,
        note="Higgsfield DoP hosted API — commercial terms, paid-safe",
    ),
    "runway": ModelLicense("runway", COMMERCIAL_API),
    "luma": ModelLicense("luma", COMMERCIAL_API),
    "veo": ModelLicense("veo", COMMERCIAL_API),
    "seedance": ModelLicense("seedance", COMMERCIAL_API),
    "suno": ModelLicense("suno", COMMERCIAL_API),
    "aiva": ModelLicense("aiva", COMMERCIAL_API),
    # Hosted vendor APIs (commercial terms of the vendor's own API).
    "openai": ModelLicense("openai", COMMERCIAL_API),
    "anthropic": ModelLicense("anthropic", COMMERCIAL_API),
    "openrouter": ModelLicense("openrouter", COMMERCIAL_API, note="hosted LLM text routes via OpenRouter"),
    "google": ModelLicense("google", COMMERCIAL_API, note="Gemini / Imagen / Veo via Google's API"),
    "elevenlabs": ModelLicense("elevenlabs", COMMERCIAL_API),
    "cartesia": ModelLicense("cartesia", COMMERCIAL_API),
    "playht": ModelLicense("playht", COMMERCIAL_API),
    "minimax": ModelLicense("minimax", COMMERCIAL_API, note="Hailuo / speech hosted API"),
    "heygen": ModelLicense("heygen", COMMERCIAL_API),
    "did": ModelLicense("did", COMMERCIAL_API),
    "pika": ModelLicense("pika", COMMERCIAL_API),
    "pixverse": ModelLicense("pixverse", COMMERCIAL_API),
    "bytedance": ModelLicense("bytedance", COMMERCIAL_API, note="Seedance / Seedream hosted API"),
    "recraft": ModelLicense("recraft", COMMERCIAL_API),
    "ideogram": ModelLicense("ideogram", COMMERCIAL_API),
    "udio": ModelLicense("udio", COMMERCIAL_API),
    "bfl_api": ModelLicense(
        "bfl_api", COMMERCIAL_API, note="FLUX 1.1 [pro] / [pro] ultra — BFL API terms, commercial OK",
    ),
    "kokoro": ModelLicense("kokoro", PERMISSIVE, note="Apache-2.0 — commercial OK"),
    "chatterbox": ModelLicense("chatterbox", PERMISSIVE, note="MIT — commercial OK"),
    # Open weights, commercial-friendly.
    "wan22": ModelLicense("wan22", RESTRICTED, note="Apache-2.0 weights — commercial OK"),
    "wan_camera": ModelLicense(
        "wan_camera", RESTRICTED,
        note="Wan2.2-Fun-A14B camera control — open weights (Apache-2.0), commercial OK",
    ),
    "ltx": ModelLicense("ltx", RESTRICTED, note="LTX-Video open weights licence — commercial OK with conditions"),
    "cogvideox": ModelLicense(
        "cogvideox", RESTRICTED,
        note="CogVideoX-2B Apache-2.0; 5B under the CogVideoX License (commercial with registration)",
    ),
    "svd": ModelLicense(
        "svd", RESTRICTED,
        note="Stable Video Diffusion — Stability AI Community License, commercial OK under revenue cap",
    ),
    "animatediff": ModelLicense(
        "animatediff", RESTRICTED,
        note="AnimateDiff — Apache-2.0 motion module; SD1.5 base (CreativeML OpenRAIL-M)",
    ),
    "mochi": ModelLicense(
        "mochi", RESTRICTED, note="Mochi-1 (Genmo) — Apache-2.0 open weights, commercial OK",
    ),
    # The bare family key is ambiguous ([dev] is non-commercial, [schnell] is
    # Apache), so it fails closed; routes name flux_schnell, flux_dev or bfl_api.
    "flux": ModelLicense(
        "flux", UNREVIEWED, note="ambiguous family key; use flux_schnell, flux_dev or bfl_api",
    ),
    "flux_schnell": ModelLicense("flux_schnell", PERMISSIVE, note="FLUX.1 [schnell] — Apache-2.0"),
    "flux2_klein_4b": ModelLicense("flux2_klein_4b", PERMISSIVE, note="FLUX.2 [klein] 4B — Apache-2.0"),
    "z_image": ModelLicense("z_image", PERMISSIVE, note="Z-Image — Apache-2.0"),
    "qwen_image": ModelLicense("qwen_image", PERMISSIVE, note="Qwen-Image — Apache-2.0"),
    "hidream": ModelLicense("hidream", PERMISSIVE, note="HiDream-I1 — MIT"),
    "omnigen2": ModelLicense("omnigen2", PERMISSIVE, note="OmniGen2 — Apache-2.0"),
    "auraflow": ModelLicense("auraflow", PERMISSIVE, note="AuraFlow — Apache-2.0"),
    "stability": ModelLicense(
        "stability", RESTRICTED,
        note="SDXL / SD 3.5 — Stability AI Community License, commercial OK under revenue cap",
    ),
    "playground": ModelLicense(
        "playground", RESTRICTED, note="Playground v2.5 Community License — commercial OK with conditions",
    ),
    "musetalk": ModelLicense("musetalk", RESTRICTED, note="MuseTalk 1.5 — MIT code and weights"),
    "ace_step": ModelLicense("ace_step", PERMISSIVE, note="ACE-Step 1.5 — MIT; replaces MusicGen"),
    "rembg": ModelLicense("rembg", PERMISSIVE, note="rembg + BiRefNet — MIT"),
    # MO1: fail closed until a MediaPipe-only fork ships (MO12b). LatentSync's
    # face_detector.py uses InsightFace (non-commercial models); 1.6 weights are OpenRAIL++.
    "latentsync": ModelLicense(
        "latentsync", NON_COMMERCIAL,
        note="InsightFace dependency (non-commercial models); paid use waits for the MO12b MediaPipe fork",
    ),
    # NON-COMMERCIAL / research — BLOCK for paying users.
    "hunyuanvideo": ModelLicense(
        "hunyuanvideo", NON_COMMERCIAL,
        note="Tencent HunyuanVideo — non-commercial terms + EU/UK/KR territorial exclusion; reference-only for global",
    ),
    "xtts": ModelLicense("xtts", NON_COMMERCIAL, note="Coqui CPML — non-commercial"),
    "f5_tts": ModelLicense("f5_tts", NON_COMMERCIAL, note="F5-TTS weights — CC-BY-NC-4.0"),
    "wav2lip": ModelLicense("wav2lip", RESEARCH_ONLY, note="Wav2Lip — research / non-commercial use only"),
    # MO1 additions (PLAN-menivor, open-source adoption (b)).
    "musicgen": ModelLicense("musicgen", NON_COMMERCIAL, note="Meta MusicGen weights — CC-BY-NC-4.0"),
    "liveportrait": ModelLicense(
        "liveportrait", NON_COMMERCIAL, note="LivePortrait uses InsightFace (non-commercial models)",
    ),
    "mmaudio": ModelLicense("mmaudio", NON_COMMERCIAL, note="MMAudio weights — CC-BY-NC-4.0"),
    "flux_dev": ModelLicense(
        "flux_dev", NON_COMMERCIAL, note="FLUX.1 [dev] Non-Commercial License",
    ),
    "flux_krea": ModelLicense(
        "flux_krea", NON_COMMERCIAL, note="FLUX.1 Krea [dev] — same FLUX.1 [dev] Non-Commercial License",
    ),
    "flux2_klein_9b": ModelLicense(
        "flux2_klein_9b", NON_COMMERCIAL, note="FLUX.2 [klein] 9B — FLUX Non-Commercial License",
    ),
    "rmbg2": ModelLicense("rmbg2", NON_COMMERCIAL, note="BRIA RMBG-2.0 weights — CC-BY-NC-4.0"),
    # Weights licence not yet recorded with a source: blocked for paid until
    # MH0 re-classifies the row with a source URL and a date.
    "sana": ModelLicense(
        "sana", RESTRICTED,
        note="NVIDIA Sana 1600M weights Apache-2.0; Gemma-2 text encoder under the Gemma Terms and "
        "Prohibited Use Policy (MH0). Source "
        "https://huggingface.co/Efficient-Large-Model/Sana_1600M_1024px_diffusers read 2026-09-29",
    ),
    "kolors": ModelLicense("kolors", UNREVIEWED, note="Kolors — weights need Kuaishou commercial registration"),
    "sadtalker": ModelLicense("sadtalker", UNREVIEWED, note="SadTalker — face-enhancer weights to review"),
    "edge_tts": ModelLicense(
        "edge_tts", UNREVIEWED,
        note="Edge read-aloud endpoint (unofficial); kept as the free fallback voice, not a sold catalog SKU",
    ),
    # MH0 (2026-09-29) rows for the current-generation catalog.
    "ltx2": ModelLicense(
        "ltx2", RESTRICTED,
        note="LTX-2 Community License: commercial use only below $10M annual revenue "
        "(OD9 yes, cap recorded; re-check before crossing it). "
        "Source https://github.com/Lightricks/LTX-2 read 2026-09-29",
    ),
    "infinitetalk": ModelLicense(
        "infinitetalk", PERMISSIVE,
        note="MeiGen InfiniteTalk: Apache-2.0 on Wan2.1-14B weights. "
        "Source https://github.com/MeiGen-AI/InfiniteTalk read 2026-09-29",
    ),
    "seedvr2": ModelLicense(
        "seedvr2", PERMISSIVE,
        note="ByteDance SeedVR2: Apache-2.0 weights. Source https://github.com/ByteDance-Seed/SeedVR read 2026-09-29",
    ),
    "stable_audio_api": ModelLicense(
        "stable_audio_api", COMMERCIAL_API,
        note="Stable Audio 2.5 through Stability AI's hosted API (official Replicate model), vendor terms. "
        "Read 2026-10-05 from https://replicate.com/stability-ai/stable-audio-2.5",
    ),
    "sync": ModelLicense(
        "sync", COMMERCIAL_API, note="sync. lipsync-2 hosted API (via fal), vendor commercial terms",
    ),
    "wan25": ModelLicense(
        "wan25", COMMERCIAL_API,
        note="Alibaba Wan 2.5 preview: hosted API only (no open weights), vendor terms via fal",
    ),
    # QM1.1 (2026-09-30) image rows. Sources: https://developers.openai.com/api/docs/deprecations and
    # https://ai.google.dev/gemini-api/docs/pricing, read 2026-09-30.
    "gpt_image_1": ModelLicense(
        "gpt_image_1", COMMERCIAL_API, sunset_on=date(2026, 10, 23), replacement="openai/gpt-image-2.5-flare",
        note="OpenAI gpt-image-1 shuts down 2026-10-23; routing falls over to GPT Image 2.5 Flare",
    ),
    "dall_e": ModelLicense(
        "dall_e", COMMERCIAL_API, sunset_on=date(2026, 5, 12), replacement="openai/gpt-image-2.5-flare",
        note="OpenAI DALL-E 2 and 3 were shut down 2026-05-12; rows kept in history, hidden from routing",
    ),
    "gpt_image_25": ModelLicense(
        "gpt_image_25", COMMERCIAL_API, note="OpenAI GPT Image 2.5 (Flare) via fal, vendor commercial terms",
    ),
    "nano_banana": ModelLicense(
        "nano_banana", COMMERCIAL_API, sunset_on=date(2026, 10, 2), replacement="google/nano-banana-2",
        note="Gemini 2.5 Flash Image shuts down 2026-10-02; routing falls over to Nano Banana 2",
    ),
    "nano_banana_2": ModelLicense(
        "nano_banana_2", COMMERCIAL_API, note="Gemini 3.1 Flash Image (Nano Banana 2) via fal, Google API terms",
    ),
    "nano_banana_pro": ModelLicense(
        "nano_banana_pro", COMMERCIAL_API, note="Gemini 3 Pro Image (Nano Banana Pro) via Replicate, Google API terms",
    ),
    # Sunset-aware.
    "sora2": ModelLicense(
        "sora2", COMMERCIAL_API, sunset_on=date(2026, 9, 24),
        replacement="veo", note="OpenAI Sora 2 API removal — migrate to routed Veo/Kling/Seedance",
    ),
}


class LicenseError(ValueError):
    """A route/deploy was attempted against a disallowed model."""


def get_license(model_key: str) -> ModelLicense | None:
    return _LICENSES.get(str(model_key or "").strip().lower())


# --------------------------------------------------------------------------- #
# Public model id -> licence key (MO1 paid gate)
# --------------------------------------------------------------------------- #
# Catalog / gateway model ids ("vendor/model") resolve to a licence key above.
# Exact ids win over vendor prefixes, so an open-weight model hosted by a vendor
# namespace (``black-forest-labs/flux-dev``) is never mistaken for that vendor's
# commercial API. An id that resolves to nothing is NOT sellable (fail closed).
_MODEL_ID_KEYS: dict[str, str] = {
    # FLUX family: only [pro] via the BFL API and [schnell] (Apache) are paid-safe.
    "black-forest-labs/flux-dev": "flux_dev",
    "black-forest-labs/flux-krea": "flux_krea",
    "black-forest-labs/flux-schnell": "flux_schnell",
    "black-forest-labs/flux-schnell-replicate": "flux_schnell",
    "black-forest-labs/flux-1.1-pro": "bfl_api",
    "black-forest-labs/flux-1.1-pro-ultra": "bfl_api",
    "black-forest-labs/flux-1.1-pro-replicate": "bfl_api",
    "black-forest-labs/flux-2-klein-9b": "flux2_klein_9b",
    "black-forest-labs/flux-2-klein-4b": "flux2_klein_4b",
    # Open-weight video on hosted queues.
    "tencent/hunyuan-video": "hunyuanvideo",
    "tencent/hunyuan-video-replicate": "hunyuanvideo",
    "hunyuanvideo/hunyuanvideo": "hunyuanvideo",
    "genmo/mochi-1": "mochi",
    "mochi/mochi-1": "mochi",
    "lightricks/ltx-video": "ltx",
    "lightricks/ltx-video-replicate": "ltx",
    "ltx_fal/ltx-video": "ltx",
    "thudm/cogvideox-5b": "cogvideox",
    "cogvideox/cogvideox-2b": "cogvideox",
    "alibaba/wan-2.2-fal": "wan22",
    "svd/stable-video-diffusion": "svd",
    "animatediff/animatediff-v1": "animatediff",
    # Open-weight image on hosted queues.
    "fal/aura-flow": "auraflow",
    "nvidia/sana": "sana",
    "kwai/kolors": "kolors",
    "shitao/omnigen-v2": "omnigen2",
    "hidream/hidream-i1": "hidream",
    "qwen/qwen-image": "qwen_image",
    "playground/playground-v2.5": "playground",
    "playgroundai/playground-v2.5": "playground",
    # MH0 current-generation rows.
    "lightricks/ltx-2": "ltx2",
    "meigen/infinitetalk": "infinitetalk",
    "bytedance/seedvr2-upscale": "seedvr2",
    "sync/lipsync-2": "sync",
    "alibaba/wan-2.5": "wan25",
    "black-forest-labs/flux-kontext-pro": "bfl_api",
    "black-forest-labs/flux-kontext-pro-replicate": "bfl_api",
    "stability-ai/stable-audio-2.5": "stable_audio_api",
    "zsxkib/mmaudio": "mmaudio",
    # QM1.1 image rows with end dates.
    "openai/gpt-image-1": "gpt_image_1",
    "openai/dall-e-3": "dall_e",
    "openai/dall-e-2": "dall_e",
    "openai/gpt-image-2.5-flare": "gpt_image_25",
    "google/nano-banana": "nano_banana",
    "google/nano-banana-2": "nano_banana_2",
    "google/nano-banana-pro-replicate": "nano_banana_pro",
    # Self-hosted voices and presenters.
    "tts/kokoro": "kokoro",
    "kokoro/tts": "kokoro",
    "tts/chatterbox": "chatterbox",
    "chatterbox/tts": "chatterbox",
    "edge/tts": "edge_tts",
    "sadtalker/photo-avatar": "sadtalker",
    # Music.
    "meta/musicgen-large": "musicgen",
    "meta/musicgen-medium": "musicgen",
    "meta/musicgen-small": "musicgen",
}

# Vendor namespace -> licence key, for hosted commercial APIs.
_VENDOR_KEYS: dict[str, str] = {
    "anthropic": "anthropic",
    "openrouter": "openrouter",
    "openai": "openai",
    "google": "google",
    "elevenlabs": "elevenlabs",
    "cartesia": "cartesia",
    "playht": "playht",
    "minimax": "minimax",
    "heygen": "heygen",
    "did": "did",
    "kwaivgi": "kling",
    "kling": "kling",
    "lumalabs": "luma",
    "luma": "luma",
    "runwayml": "runway",
    "runway": "runway",
    "pika": "pika",
    "pixverse": "pixverse",
    "bytedance": "bytedance",
    "bytedance-seed": "bytedance",
    "recraft": "recraft",
    "recraft-ai": "recraft",
    "ideogram": "ideogram",
    "ideogram-ai": "ideogram",
    "stability": "stability",
    "stabilityai": "stability",
    "stability-ai": "stability",
    "suno": "suno",
    "udio": "udio",
    "higgsfield": "higgsfield",
    "wan": "wan22",
    "pixelle": "wan22",
}


def license_key_for_model(model_id: str) -> str | None:
    """Resolve a public ``vendor/model`` id (or a bare licence key) to a licence key.

    Returns ``None`` when the id has no recorded licence; callers treat that as
    not sellable (fail closed).
    """
    mid = str(model_id or "").strip().lower()
    if not mid:
        return None
    if mid in _MODEL_ID_KEYS:
        return _MODEL_ID_KEYS[mid]
    if "/" not in mid:
        return mid if mid in _LICENSES else None
    vendor = mid.split("/", 1)[0]
    return _VENDOR_KEYS.get(vendor)


def model_license(model_id: str) -> ModelLicense | None:
    """The :class:`ModelLicense` for a public model id, or ``None`` when unrecorded."""
    key = license_key_for_model(model_id)
    return _LICENSES.get(key) if key else None


def is_model_sellable(model_id: str) -> bool:
    """True when a paying user may be charged for ``model_id`` (fail closed).

    Unlike :func:`is_paid_safe` (which keeps its historic "unknown key = hosted
    API" default for the bare-key callers), a public catalog/gateway model id
    with no recorded licence is NOT sellable.
    """
    lic = model_license(model_id)
    return lic is not None and lic.license_class not in _BLOCK_FOR_PAID


def assert_model_sellable(model_id: str) -> None:
    """Raise :class:`LicenseError` when ``model_id`` may not be sold to a paying user."""
    if is_model_sellable(model_id):
        return
    lic = model_license(model_id)
    if lic is None:
        raise LicenseError(f"{model_id!r} has no recorded licence; blocked for paying users")
    raise LicenseError(f"{model_id!r} is {lic.license_class}; blocked for paying users")


def all_licenses() -> tuple[ModelLicense, ...]:
    """Every recorded licence row (read-only snapshot, for the docs and the matrix test)."""
    return tuple(_LICENSES.values())


def is_paid_safe(model_key: str) -> bool:
    """True when a PAYING user may use this model's weights (not NC/research)."""
    lic = get_license(model_key)
    if lic is None:
        return True  # unknown = assume hosted commercial API (curated catalog gate upstream)
    return lic.license_class not in _BLOCK_FOR_PAID


def is_sunset(model_key: str, *, on: date, leeway_days: int = 0) -> bool:
    """True when the model is past (or within ``leeway_days`` of) its sunset date."""
    lic = get_license(model_key)
    if lic is None or lic.sunset_on is None:
        return False
    from datetime import timedelta

    return on >= (lic.sunset_on - timedelta(days=max(0, leeway_days)))


def sunset_status(model_key: str, *, on: date) -> dict:
    """Migration advisory for a model: {sunset, days_left, replacement}."""
    lic = get_license(model_key)
    if lic is None or lic.sunset_on is None:
        return {"sunset": False, "days_left": None, "replacement": ""}
    days_left = (lic.sunset_on - on).days
    return {
        "sunset": days_left <= 0,
        "days_left": days_left,
        "replacement": lic.replacement,
        "note": lic.note,
    }


def is_route_allowed(model_key: str, *, paid: bool, on: date) -> bool:
    """The route-time gate: block NC/research for paid, and block sunset models."""
    if paid and not is_paid_safe(model_key):
        return False
    if is_sunset(model_key, on=on):
        return False
    return True


def assert_route_allowed(model_key: str, *, paid: bool, on: date) -> None:
    """Raise :class:`LicenseError` when a route is not allowed (deploy/route gate)."""
    lic = get_license(model_key)
    if paid and not is_paid_safe(model_key):
        cls = lic.license_class if lic else "unknown"
        raise LicenseError(f"{model_key!r} is {cls}; blocked for paying users")
    if is_sunset(model_key, on=on):
        repl = lic.replacement if lic else ""
        raise LicenseError(
            f"{model_key!r} is past its sunset date; migrate to {repl or 'a supported model'}"
        )
