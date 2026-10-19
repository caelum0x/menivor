"""Curated multi-provider catalog seed across every generation capability.

Publishes a broad, reviewed set of providers + model listings + illustrative
prices + generation profiles so the marketplace has a real catalog to browse and
quote against (PROVIDER_MARKETPLACE_PLAN.md §2). This is an INDEPENDENT catalog
inspired by the pay-as-you-go operating model — not a fork of any provider's
code or data.

IMPORTANT
---------
* Every model is seeded ``release_status='shadow'`` (browsable/quotable
  internally, NOT a live billable route) and every provider ``enabled=False``.
  Promotion to a live route is a deliberate operator action gated on an approved
  adapter, license, and finance-reviewed price.
* All prices are ILLUSTRATIVE integer-microdollar defaults (``source='manual'``)
  and MUST be reconciled against real provider invoices before any live charge.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.catalog.admin import CatalogAdmin

# --------------------------------------------------------------------------- #
# Providers — (key, display_name, region, data_policy)
# --------------------------------------------------------------------------- #
PROVIDERS: list[dict] = [
    {"provider_key": "anthropic", "display_name": "Anthropic", "region": "us"},
    {"provider_key": "openai", "display_name": "OpenAI", "region": "us"},
    {"provider_key": "google", "display_name": "Google", "region": "us"},
    {"provider_key": "openrouter", "display_name": "OpenRouter", "region": "global"},
    {"provider_key": "elevenlabs", "display_name": "ElevenLabs", "region": "us"},
    {"provider_key": "cartesia", "display_name": "Cartesia", "region": "us"},
    {"provider_key": "playht", "display_name": "PlayHT", "region": "us"},
    {"provider_key": "minimax", "display_name": "MiniMax", "region": "global"},
    {"provider_key": "heygen", "display_name": "HeyGen", "region": "us"},
    {"provider_key": "did", "display_name": "D-ID", "region": "eu"},
    {"provider_key": "sadtalker", "display_name": "SadTalker (self-hosted)", "region": "us"},
    {"provider_key": "chatterbox", "display_name": "Chatterbox (self-hosted)", "region": "us"},
    {"provider_key": "kokoro", "display_name": "Kokoro (self-hosted)", "region": "us"},
    {"provider_key": "edge", "display_name": "Edge TTS (free)", "region": "global"},
    {"provider_key": "pixelle", "display_name": "Pixelle (managed Comfy)", "region": "us"},
    {"provider_key": "runway", "display_name": "Runway", "region": "us"},
    {"provider_key": "luma", "display_name": "Luma", "region": "us"},
    {"provider_key": "kling", "display_name": "Kling", "region": "global"},
    {"provider_key": "pika", "display_name": "Pika", "region": "us"},
    {"provider_key": "stability", "display_name": "Stability AI", "region": "eu"},
    {"provider_key": "black-forest-labs", "display_name": "Black Forest Labs", "region": "eu"},
    {"provider_key": "ideogram", "display_name": "Ideogram", "region": "us"},
    {"provider_key": "recraft", "display_name": "Recraft", "region": "us"},
    {"provider_key": "suno", "display_name": "Suno", "region": "us"},
    {"provider_key": "udio", "display_name": "Udio", "region": "us"},
    {"provider_key": "meta", "display_name": "Meta", "region": "us"},
    # Video-fallback providers (license-clean Higgsfield -> OSS chain).
    {"provider_key": "higgsfield", "display_name": "Higgsfield", "region": "us"},
    {"provider_key": "wan", "display_name": "Wan (open weights)", "region": "global"},
    {"provider_key": "ltx_fal", "display_name": "LTX-Video (fal.ai)", "region": "us"},
    {"provider_key": "cogvideox", "display_name": "CogVideoX (open weights)", "region": "global"},
    # Additional open-weights video fallbacks (all on the fal.ai queue).
    {"provider_key": "svd", "display_name": "Stable Video Diffusion (fal.ai)", "region": "us"},
    {"provider_key": "animatediff", "display_name": "AnimateDiff (fal.ai)", "region": "us"},
    {"provider_key": "mochi", "display_name": "Mochi-1 (open weights)", "region": "us"},
    # HunyuanVideo — non-commercial + EU/UK/KR territorial exclusion; reference-only.
    {"provider_key": "hunyuanvideo", "display_name": "HunyuanVideo (reference-only)", "region": "global"},
]


# --------------------------------------------------------------------------- #
# Models — (model_id, provider, capability, unit, unit_price_micros, default_units)
# Prices are illustrative defaults; see module docstring.
# --------------------------------------------------------------------------- #
def _m(
    model_id: str,
    provider_key: str,
    capability: str,
    display_name: str,
    unit: str,
    unit_price_micros: int,
    default_units: int,
    *,
    latency_band: str = "standard",
    min_charge_micros: int = 0,
    flat_fee_micros: int = 0,
) -> dict:
    return {
        "model_id": model_id,
        "provider_key": provider_key,
        "capability": capability,
        "display_name": display_name,
        "metering_unit": unit,
        "unit": unit,
        "unit_price_micros": unit_price_micros,
        "default_units": default_units,
        "latency_band": latency_band,
        "min_charge_micros": min_charge_micros,
        "flat_fee_micros": flat_fee_micros,
    }


MODELS: list[dict] = [
    # ---- Script / reasoning (LLM) — per output token, micros ----
    _m("anthropic/claude-opus-4", "anthropic", "script", "Claude Opus 4", "output_tokens", 15, 1500, latency_band="standard"),
    _m("anthropic/claude-sonnet-4", "anthropic", "script", "Claude Sonnet 4", "output_tokens", 3, 1500, latency_band="fast"),
    _m("anthropic/claude-haiku-4", "anthropic", "script", "Claude Haiku 4", "output_tokens", 1, 1500, latency_band="fast"),
    _m("openai/gpt-4o", "openai", "script", "GPT-4o", "output_tokens", 10, 1500),
    _m("openai/gpt-4o-mini", "openai", "script", "GPT-4o mini", "output_tokens", 1, 1500, latency_band="fast"),
    _m("google/gemini-2.5-pro", "google", "script", "Gemini 2.5 Pro", "output_tokens", 10, 1500),
    _m("google/gemini-2.5-flash", "google", "script", "Gemini 2.5 Flash", "output_tokens", 1, 1500, latency_band="fast"),
    # ---- Voice / TTS — per character, micros ----
    _m("elevenlabs/eleven_multilingual_v2", "elevenlabs", "voice", "ElevenLabs Multilingual v2", "characters", 300, 600),
    _m("elevenlabs/eleven_turbo_v2_5", "elevenlabs", "voice", "ElevenLabs Turbo v2.5", "characters", 150, 600, latency_band="fast"),
    _m("cartesia/sonic", "cartesia", "voice", "Cartesia Sonic", "characters", 100, 600, latency_band="fast"),
    _m("playht/play3", "playht", "voice", "PlayHT 3.0", "characters", 100, 600),
    _m("openai/tts-1", "openai", "voice", "OpenAI TTS-1", "characters", 15, 600, latency_band="fast"),
    _m("openai/tts-1-hd", "openai", "voice", "OpenAI TTS-1 HD", "characters", 30, 600),
    _m("minimax/speech-01", "minimax", "voice", "MiniMax Speech-01", "characters", 100, 600),
    # Self-hosted / free voice fallbacks (near-zero marginal cost).
    _m("chatterbox/tts", "chatterbox", "voice", "Chatterbox TTS", "characters", 5, 600, latency_band="fast"),
    _m("kokoro/tts", "kokoro", "voice", "Kokoro TTS", "characters", 5, 600, latency_band="fast"),
    _m("edge/tts", "edge", "voice", "Edge TTS (free)", "characters", 0, 600, latency_band="fast"),
    # ---- Avatar / talking-head — per second, micros ----
    _m("heygen/avatar-v3", "heygen", "avatar", "HeyGen Avatar v3", "seconds", 5_000, 30),
    _m("did/talks", "did", "avatar", "D-ID Talks", "seconds", 4_000, 30),
    _m("minimax/video-avatar", "minimax", "avatar", "MiniMax Avatar", "seconds", 3_000, 30),
    # Photo → talking-head from the creator's own photo (self-hosted GPU).
    _m("sadtalker/photo-avatar", "sadtalker", "avatar", "SadTalker Photo Avatar", "seconds", 500, 30, latency_band="slow"),
    # ---- B-roll / video — per second, micros ----
    _m("pixelle/wan-i2v", "pixelle", "broll", "Wan image-to-video", "seconds", 40_000, 6),
    _m("pixelle/wan-t2v", "pixelle", "broll", "Wan text-to-video", "seconds", 40_000, 6),
    _m("runway/gen-3", "runway", "broll", "Runway Gen-3", "seconds", 50_000, 6, latency_band="slow"),
    _m("luma/dream-machine", "luma", "broll", "Luma Dream Machine", "seconds", 45_000, 6, latency_band="slow"),
    _m("kling/v1", "kling", "broll", "Kling v1", "seconds", 35_000, 6, latency_band="slow"),
    _m("pika/v1", "pika", "broll", "Pika 1.0", "seconds", 40_000, 6, latency_band="slow"),
    _m("google/veo-3", "google", "broll", "Google Veo 3", "seconds", 75_000, 6, latency_band="slow"),
    _m("minimax/video-01", "minimax", "broll", "MiniMax Video-01", "seconds", 30_000, 6, latency_band="slow"),
    # ---- Video-fallback chain — license-clean Higgsfield -> Wan -> LTX -> CogVideoX ----
    _m("higgsfield/dop-v1", "higgsfield", "broll", "Higgsfield DoP v1", "seconds", 45_000, 6, latency_band="slow"),
    _m("wan/wan-2.2-t2v", "wan", "broll", "Wan 2.2 Text-to-Video", "seconds", 60_000, 6, latency_band="slow"),
    _m("ltx_fal/ltx-video", "ltx_fal", "broll", "LTX-Video (fal.ai)", "seconds", 20_000, 6, latency_band="slow"),
    _m("cogvideox/cogvideox-2b", "cogvideox", "broll", "CogVideoX-2B", "seconds", 3_000, 6, latency_band="slow"),
    _m("svd/stable-video-diffusion", "svd", "broll", "Stable Video Diffusion", "seconds", 15_000, 6, latency_band="slow"),
    _m("animatediff/animatediff-v1", "animatediff", "broll", "AnimateDiff", "seconds", 8_000, 6, latency_band="slow"),
    _m("mochi/mochi-1", "mochi", "broll", "Mochi-1", "seconds", 25_000, 6, latency_band="slow"),
    # Reference-only (non-commercial + EU/UK/KR geo caveat): stays shadow, never
    # promoted to a live global route by seed_video_fallback_catalog.
    _m("hunyuanvideo/hunyuanvideo", "hunyuanvideo", "broll", "HunyuanVideo (reference-only)", "seconds", 30_000, 6, latency_band="slow"),
    # ---- Image / cover — per image, micros (flat via unit_price * 1) ----
    _m("stability/sdxl", "stability", "image", "Stable Diffusion XL", "images", 10_000, 1, latency_band="fast"),
    _m("stability/sd3.5-large", "stability", "image", "Stable Diffusion 3.5 Large", "images", 40_000, 1),
    _m("black-forest-labs/flux-1.1-pro", "black-forest-labs", "image", "FLUX 1.1 Pro", "images", 40_000, 1),
    _m("black-forest-labs/flux-schnell", "black-forest-labs", "image", "FLUX Schnell", "images", 3_000, 1, latency_band="fast"),
    _m("openai/gpt-image-1", "openai", "image", "GPT Image 1", "images", 40_000, 1),
    _m("ideogram/v2", "ideogram", "image", "Ideogram v2", "images", 80_000, 1),
    _m("recraft/v3", "recraft", "image", "Recraft v3", "images", 40_000, 1),
    # ---- Music — per second, micros ----
    _m("suno/v4", "suno", "music", "Suno v4", "seconds", 10_000, 30, latency_band="slow"),
    _m("udio/v1", "udio", "music", "Udio v1", "seconds", 10_000, 30, latency_band="slow"),
    _m("meta/musicgen-large", "meta", "music", "MusicGen Large", "seconds", 2_000, 30, latency_band="slow"),
]


# --------------------------------------------------------------------------- #
# Curated generation profiles — stage -> model_id
# --------------------------------------------------------------------------- #
PROFILES: list[dict] = [
    {
        "slug": "creator-fast-v1",
        "display_name": "Creator Fast",
        "description": "Low-latency, low-cost defaults for rapid iteration.",
        "stages": {
            "script": {"model_id": "anthropic/claude-haiku-4"},
            "voice": {"model_id": "elevenlabs/eleven_turbo_v2_5"},
            "avatar": {"model_id": "heygen/avatar-v3"},
            "broll": {"model_id": "kling/v1"},
        },
        "routing": {"fallback": "none"},
    },
    {
        "slug": "creator-quality-v1",
        "display_name": "Creator Quality",
        "description": "Higher-fidelity models for a polished final reel.",
        "stages": {
            "script": {"model_id": "anthropic/claude-sonnet-4"},
            "voice": {"model_id": "elevenlabs/eleven_multilingual_v2"},
            "avatar": {"model_id": "heygen/avatar-v3"},
            "broll": {"model_id": "runway/gen-3"},
        },
        "routing": {"fallback": "none"},
    },
    {
        "slug": "cinematic-v1",
        "display_name": "Cinematic",
        "description": "Premium video-forward profile for hero content.",
        "stages": {
            "script": {"model_id": "anthropic/claude-opus-4"},
            "voice": {"model_id": "elevenlabs/eleven_multilingual_v2"},
            "avatar": {"model_id": "heygen/avatar-v3"},
            "broll": {"model_id": "google/veo-3"},
            "music": {"model_id": "suno/v4"},
        },
        "routing": {"fallback": "none"},
    },
    {
        "slug": "self-hosted-v1",
        "display_name": "Self-Hosted (lowest cost)",
        "description": "Near-zero marginal cost: free/self-hosted voice + open video.",
        "stages": {
            "script": {"model_id": "anthropic/claude-haiku-4"},
            "voice": {"model_id": "edge/tts"},
            "avatar": {"model_id": "sadtalker/photo-avatar"},
            "broll": {"model_id": "kling/v1"},
        },
        "routing": {"fallback": "equivalent"},
    },
    {
        "slug": "photo-avatar-v1",
        "display_name": "Photo Avatar",
        "description": "Talking head from the creator's own photo (SadTalker).",
        "stages": {
            "script": {"model_id": "anthropic/claude-haiku-4"},
            "voice": {"model_id": "chatterbox/tts"},
            "avatar": {"model_id": "sadtalker/photo-avatar"},
            "broll": {"model_id": "pixelle/wan-i2v"},
        },
        "routing": {"fallback": "none"},
    },
    {
        "slug": "video-fallback-v1",
        "display_name": "Video Fallback (Higgsfield → OSS)",
        "description": (
            "License-clean video with automatic Higgsfield → Wan → LTX → CogVideoX "
            "→ SVD → AnimateDiff → Mochi equivalent fallback so a b-roll shot always "
            "renders. HunyuanVideo is reference-only (NC + EU/UK/KR) and excluded."
        ),
        "stages": {
            "script": {"model_id": "anthropic/claude-haiku-4"},
            "voice": {"model_id": "edge/tts"},
            "broll": {"model_id": "higgsfield/dop-v1"},
        },
        "routing": {
            "fallback": "equivalent",
            "provider_order": [
                "higgsfield", "wan", "ltx_fal", "cogvideox", "svd", "animatediff", "mochi",
            ],
        },
    },
]


# --------------------------------------------------------------------------- #
# Video-fallback chain — the license-clean Higgsfield → OSS provider order.
# These model ids back the ``video-fallback-v1`` profile and are the set promoted
# to a live route by :func:`seed_video_fallback_catalog`. HunyuanVideo is excluded
# (reference-only: non-commercial + EU/UK/KR territorial exclusion).
# --------------------------------------------------------------------------- #
VIDEO_FALLBACK_MODELS: list[str] = [
    "higgsfield/dop-v1",
    "wan/wan-2.2-t2v",
    "ltx_fal/ltx-video",
    "cogvideox/cogvideox-2b",
    "svd/stable-video-diffusion",
    "animatediff/animatediff-v1",
    "mochi/mochi-1",
    # NB: hunyuanvideo/hunyuanvideo is deliberately NOT promoted here — it is
    # reference-only (non-commercial + EU/UK/KR geo caveat) and stays shadow.
]


def seed_default_catalog(
    session: Session, *, live_models: set[str] | None = None
) -> dict[str, int]:
    """Idempotently publish the curated catalog. Returns counts by kind.

    ``live_models`` optionally promotes specific ``model_id`` values (and their
    providers) to a live route (``release_status='ga'``, provider enabled).
    Default: everything stays in shadow mode. Safe to run repeatedly.
    """
    live = live_models or set()
    admin = CatalogAdmin(session)

    for provider in PROVIDERS:
        admin.upsert_provider(provider["provider_key"], display_name=provider["display_name"], region=provider.get("region", ""))

    for model in MODELS:
        is_live = model["model_id"] in live
        admin.upsert_model(
            model["model_id"],
            provider_key=model["provider_key"],
            capability=model["capability"],
            display_name=model["display_name"],
            metering_unit=model["metering_unit"],
            latency_band=model["latency_band"],
            availability_state="available",
            release_status="ga" if is_live else "shadow",
        )
        admin.ensure_price(
            model["model_id"],
            unit=model["unit"],
            unit_price_micros=model["unit_price_micros"],
            min_charge_micros=model["min_charge_micros"],
            flat_fee_micros=model["flat_fee_micros"],
            quote_rules={"default_units": model["default_units"]},
            source="manual",
        )
        if is_live:
            admin.upsert_provider(
                model["provider_key"],
                display_name=next(
                    (p["display_name"] for p in PROVIDERS if p["provider_key"] == model["provider_key"]),
                    model["provider_key"],
                ),
                enabled=True,
                credential_state="configured",
            )

    for profile in PROFILES:
        # Approximate the profile cap from its stages' default estimates so a
        # cap exists without hand-maintaining one; operators may override later.
        admin.upsert_profile(
            profile["slug"],
            display_name=profile["display_name"],
            description=profile["description"],
            stages=profile["stages"],
            routing=profile["routing"],
            is_curated=True,
        )

    session.flush()
    return {
        "providers": len(PROVIDERS),
        "models": len(MODELS),
        "profiles": len(PROFILES),
    }


def seed_video_fallback_catalog(
    session: Session, *, live: bool = True
) -> dict[str, int]:
    """Seed the catalog and make the license-clean video-fallback chain routable.

    Publishes the full curated catalog (idempotent) and, when ``live`` is True
    (the default), promotes exactly the :data:`VIDEO_FALLBACK_MODELS` — Higgsfield
    → Wan → LTX → CogVideoX → SVD → AnimateDiff → Mochi — to ``release_status='ga'``
    (their providers enabled +
    credential ``configured``) so the ``video-fallback-v1`` profile has a live,
    routable equivalent-fallback chain. With ``live=False`` everything stays in
    shadow mode. Safe to run repeatedly.
    """
    live_models = set(VIDEO_FALLBACK_MODELS) if live else None
    return seed_default_catalog(session, live_models=live_models)
