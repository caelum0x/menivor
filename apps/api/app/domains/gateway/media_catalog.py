"""Unified media-model catalog (OpenRouter-style) — image + video + audio models.

One catalog mapping a public ``model`` id to its modality, upstream provider, the
provider-side model ref, and integer-microdollar pricing. The gateway
(``media_gateway``) resolves a request's ``model`` here and routes to the right
real adapter — so a single key + balance serves every image/video/audio model,
exactly like OpenRouter's ``/images`` + ``/videos`` surface.

**Coverage strategy.** fal.ai and Replicate are aggregators that host *hundreds*
of real models behind one protocol; the ``kling-fal``/``fal-image`` (fal) and
``wan``/``replicate-image`` (Replicate) adapters accept a **direct provider path**
as ``model_ref``, so every row below is a real, routable API call with no per-model
adapter code. Dedicated adapters (Runway, Veo, Luma, MiniMax, Suno) cover models
that need their own protocol. Static reviewed data (pure); the adapters do the
real API calls. Prices are integer micro-USD (video/audio caveats noted); confirm
live vendor pricing before production billing.

**MH0 (Wave D, 2026-09-29): price sources and legacy rows.** Every row carries a
``price_source`` URL and a ``price_date``:

* ``price_verified=True`` rows had their price read from ``price_source`` on
  ``price_date`` (the current-generation rows below, plus refreshed rows).
* ``legacy=True`` rows are the pre-MH0 catalog. They stay routable (nothing is
  removed) and their description starts with "Legacy:". Their ``price_date`` is
  the day the source URL was recorded, and ``price_verified`` is False until the
  weekly drift check (``app/services/loops/price_drift.py``) reads a live price.
* ``internal:`` sources mark self-hosted rows priced from our own compute cost.

**QM1.1 (Wave Q, 2026-09-30): end dates and successors.** A row may carry
``retired_on`` (the vendor's shutdown date) and a ``successor``. Rows are never
deleted: :func:`history_rows` keeps them, :func:`get_row` reads them, and
routing hides them. With ``fallover=True`` (gpt-image-1, Nano Banana) routing
moves to the successor ``FALLOVER_LEAD_DAYS`` before the end date; without it
(DALL-E 2 and 3) the gateway answers 410 naming the successor.

Stage models (lipsync, talking avatar, video upscale) need audio or video
inputs, so they are listed in ``stage_models()`` and are not served by the
prompt-only ``/media/*`` gateway. The render pipeline and the MH1 tier resolver
read them from here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone

from app.domains.routing.providers.seedance_ark import seedance_ark_model

IMAGE = "image"
#: Routing moves to a row's successor this many days before the vendor shuts it down (QM1.1).
FALLOVER_LEAD_DAYS = 3
VIDEO = "video"
AUDIO = "audio"


@dataclass(frozen=True)
class MediaModel:
    """A routable media model."""

    id: str                 # public id, e.g. "google/veo-3.1-lite"
    modality: str           # image | video | audio
    provider: str           # upstream adapter key: kling-fal | fal-image | veo | runway | wan | replicate-image | imagen | openai-image | luma | minimax | suno | elevenlabs | tts | heygen | ark
    model_ref: str          # provider-side model id / path
    price_micros: int       # per-unit price (image: per image; video: per second; audio: per clip)
    unit: str               # "image" | "second" | "clip"
    max_seconds: int = 0    # video only
    description: str = ""
    price_source: str = ""  # URL the price was read from ("internal:..." for self-hosted)
    price_date: str = ""    # ISO date the price (or, for legacy rows, the source) was recorded
    price_verified: bool = False  # True when price_micros was read from price_source on price_date
    legacy: bool = False    # pre-MH0 row: kept routable, relabelled "Legacy:"
    resolution: str = ""    # output resolution the price applies to (video)
    inputs: tuple[str, ...] = ("prompt",)  # "image": one first frame; "images": role-tagged references; stage models take audio/video
    retired_on: str = ""    # QM1.1: ISO date the vendor shuts the model down ("" = no end date)
    successor: str = ""     # QM1.1: the row that replaces it
    fallover: bool = False  # QM1.1: route to ``successor`` from FALLOVER_LEAD_DAYS before ``retired_on``


# --------------------------------------------------------------------------- #
# Video models (poll-to-complete)
# --------------------------------------------------------------------------- #
_VIDEO: list[MediaModel] = [
    # --- Kling family (dedicated aliases, fal.ai) ---
    MediaModel("kwaivgi/kling-v1.6", VIDEO, "kling-fal", "kling-t2v", 84_000, "second", 10,
               "Kling 1.6 standard — cheapest high-quality video (fal.ai)."),
    MediaModel("kwaivgi/kling-v1.6-i2v", VIDEO, "kling-fal", "kling-i2v", 84_000, "second", 10,
               "Kling 1.6 image-to-video."),
    MediaModel("kwaivgi/kling-v2-master", VIDEO, "kling-fal", "kling-pro-t2v", 280_000, "second", 10,
               "Kling 2 master — top realism / #1 ELO."),
    MediaModel("kwaivgi/kling-v2-master-i2v", VIDEO, "kling-fal", "kling-pro-i2v", 280_000, "second", 10,
               "Kling 2 master image-to-video."),
    MediaModel("kwaivgi/kling-v2.1-master", VIDEO, "kling-fal",
               "fal-ai/kling-video/v2.1/master/text-to-video", 280_000, "second", 10,
               "Kling 2.1 master (fal.ai)."),
    # --- Other fal-hosted video models (direct fal paths) ---
    # MH0 refresh: fal lists Hailuo-02 standard (768p) at $0.045/s; the old
    # 260_000 was about 5.8x the vendor cost.
    MediaModel("minimax/hailuo-02-fal", VIDEO, "kling-fal",
               "fal-ai/minimax/hailuo-02/standard/text-to-video", 45_000, "second", 6,
               "MiniMax Hailuo 02 standard (768p) via fal.ai.",
               price_source="https://fal.ai/models/fal-ai/minimax/hailuo-02/standard/text-to-video",
               price_date="2026-09-28", price_verified=True, resolution="768p"),
    MediaModel("lumalabs/ray-2-fal", VIDEO, "kling-fal", "fal-ai/luma-dream-machine/ray-2",
               320_000, "second", 9, "Luma Ray-2 via fal.ai."),
    MediaModel("tencent/hunyuan-video", VIDEO, "kling-fal", "fal-ai/hunyuan-video",
               180_000, "second", 6, "HunyuanVideo — open-weight T2V (fal.ai)."),
    MediaModel("genmo/mochi-1", VIDEO, "kling-fal", "fal-ai/mochi-v1", 180_000, "second", 6,
               "Mochi-1 — Apache open T2V (fal.ai)."),
    MediaModel("lightricks/ltx-video", VIDEO, "kling-fal", "fal-ai/ltx-video", 90_000, "second", 8,
               "LTX-Video — real-time DiT (fal.ai)."),
    MediaModel("thudm/cogvideox-5b", VIDEO, "kling-fal", "fal-ai/cogvideox-5b", 120_000, "second", 6,
               "CogVideoX-5B (fal.ai)."),
    MediaModel("pika/v2.2", VIDEO, "kling-fal", "fal-ai/pika/v2.2/text-to-video",
               240_000, "second", 8, "Pika 2.2 (fal.ai)."),
    MediaModel("pixverse/v4.5", VIDEO, "kling-fal", "fal-ai/pixverse/v4.5/text-to-video",
               180_000, "second", 8, "PixVerse v4.5 (fal.ai)."),
    # MH0 refresh: $0.08/s at 720p ($0.06 at 580p, $0.04 at 480p); was 120_000.
    MediaModel("alibaba/wan-2.2-fal", VIDEO, "kling-fal", "fal-ai/wan/v2.2-a14b/text-to-video",
               80_000, "second", 6, "Wan 2.2 A14B (720p) via fal.ai.",
               price_source="https://fal.ai/models/fal-ai/wan/v2.2-a14b/text-to-video",
               price_date="2026-09-29", price_verified=True, resolution="720p"),
    MediaModel("bytedance/seedance-1-pro", VIDEO, "kling-fal",
               "fal-ai/bytedance/seedance/v1/pro/text-to-video", 300_000, "second", 10,
               "Seedance 1 Pro (fal.ai)."),
    MediaModel("google/veo-3-fal", VIDEO, "kling-fal", "fal-ai/veo3", 500_000, "second", 8,
               "Veo 3 via fal.ai (native audio)."),
    # --- MH0 current generation (fal.ai; prices read from each model page 2026-09-29) ---
    # Prices are the vendor base COST per second at ``resolution``; markup is
    # applied on top in service.apply_markup.
    MediaModel("kwaivgi/kling-v2.5-turbo-pro", VIDEO, "kling-fal",
               "fal-ai/kling-video/v2.5-turbo/pro/text-to-video", 70_000, "second", 10,
               "Kling 2.5 Turbo Pro — strong default final tier ($0.35 per 5 s + $0.07/s).",
               price_source="https://fal.ai/models/fal-ai/kling-video/v2.5-turbo/pro/text-to-video",
               price_date="2026-09-29", price_verified=True, resolution="1080p"),
    MediaModel("kwaivgi/kling-v3-pro", VIDEO, "kling-fal",
               "fal-ai/kling-video/v3/pro/text-to-video", 112_000, "second", 10,
               "Kling 3.0 Pro (silent; $0.168/s with audio).",
               price_source="https://fal.ai/models/fal-ai/kling-video/v3/pro/text-to-video",
               price_date="2026-09-29", price_verified=True, resolution="1080p"),
    MediaModel("bytedance/seedance-2.0", VIDEO, "kling-fal",
               "bytedance/seedance-2.0/text-to-video", 303_400, "second", 10,
               "Seedance 2.0 at 720p with audio — cinematic tier.",
               price_source="https://fal.ai/models/bytedance/seedance-2.0/text-to-video",
               price_date="2026-09-29", price_verified=True, resolution="720p"),
    MediaModel("bytedance/seedance-2.0-fast", VIDEO, "kling-fal",
               "bytedance/seedance-2.0/fast/text-to-video", 241_900, "second", 10,
               "Seedance 2.0 Fast at 720p with audio.",
               price_source="https://fal.ai/models/bytedance/seedance-2.0/text-to-video",
               price_date="2026-09-29", price_verified=True, resolution="720p"),
    # --- Very ___ Time (2026-10-05): Seedance 2.0 image-to-video and reference-to-video ---
    # fal bills both at $0.3024/s at 720p with audio included (read from each model
    # page 2026-10-05). i2v takes one ``image_url`` (the first frame); r2v takes an
    # ``image_urls`` list the prompt names as @Image1, @Image2 ...
    MediaModel("bytedance/seedance-2.0-i2v", VIDEO, "kling-fal",
               "bytedance/seedance-2.0/image-to-video", 302_400, "second", 15,
               "Seedance 2.0 image-to-video at 720p with audio (first frame + brief).",
               price_source="https://fal.ai/models/bytedance/seedance-2.0/image-to-video",
               price_date="2026-10-05", price_verified=True, resolution="720p",
               inputs=("prompt", "image")),
    MediaModel("bytedance/seedance-2.0-r2v", VIDEO, "kling-fal",
               "bytedance/seedance-2.0/reference-to-video", 302_400, "second", 15,
               "Seedance 2.0 reference-to-video at 720p with audio (up to 4 role-tagged images).",
               price_source="https://fal.ai/models/bytedance/seedance-2.0/reference-to-video",
               price_date="2026-10-05", price_verified=True, resolution="720p",
               inputs=("prompt", "images")),
    MediaModel("google/veo-3.1-fast-fal", VIDEO, "kling-fal", "fal-ai/veo3.1/fast", 150_000, "second", 8,
               "Veo 3.1 Fast via fal.ai, with audio ($0.10/s silent).",
               price_source="https://fal.ai/models/fal-ai/veo3.1/fast",
               price_date="2026-09-29", price_verified=True, resolution="1080p"),
    MediaModel("alibaba/wan-2.5", VIDEO, "kling-fal", "fal-ai/wan-25-preview/text-to-video",
               100_000, "second", 10, "Wan 2.5 preview at 720p ($0.05/s 480p, $0.15/s 1080p).",
               price_source="https://fal.ai/models/fal-ai/wan-25-preview/text-to-video",
               price_date="2026-09-29", price_verified=True, resolution="720p"),
    MediaModel("minimax/hailuo-02-pro-fal", VIDEO, "kling-fal",
               "fal-ai/minimax/hailuo-02/pro/text-to-video", 80_000, "second", 10,
               "MiniMax Hailuo 02 Pro (1080p) via fal.ai.",
               price_source="https://fal.ai/models/fal-ai/minimax/hailuo-02/pro/text-to-video",
               price_date="2026-09-29", price_verified=True, resolution="1080p"),
    MediaModel("lightricks/ltx-2", VIDEO, "kling-fal", "fal-ai/ltx-2/text-to-video", 60_000, "second", 10,
               "LTX-2 at 1080p — fast draft tier with audio (revenue-capped licence).",
               price_source="https://fal.ai/models/fal-ai/ltx-2/text-to-video",
               price_date="2026-09-29", price_verified=True, resolution="1080p"),
    # --- Veo (dedicated Google adapter) ---
    MediaModel("google/veo-3.1", VIDEO, "veo", "veo-3.1", 400_000, "second", 8,
               "Veo 3.1 — native audio."),
    MediaModel("google/veo-3.1-lite", VIDEO, "veo", "veo-3.1-lite", 150_000, "second", 8,
               "Veo 3.1 lite — cost-efficient."),
    # --- Runway (dedicated adapter) ---
    # Price corrected 2026-09 audit: Runway Developer API bills Gen-4 Turbo and
    # Gen-3 Alpha Turbo at 5 credits/sec × $0.01/credit = $0.05/sec (flat, res-
    # independent for the turbo tiers). The prior 500_000/400_000 values were ~10×
    # the real vendor cost — this catalog is a base-COST basis (markup is applied
    # on top in service.apply_markup), so that over-estimate over-charged customers.
    # Source: https://docs.dev.runwayml.com/guides/pricing/ (Gen-4 Turbo / Gen-3a
    # Turbo = 5 credits/s; docs note a 5–6 credits/s discrepancy → $0.05–0.06/s).
    MediaModel("runwayml/gen-4", VIDEO, "runway", "gen4_turbo", 50_000, "second", 10,
               "Runway Gen-4 Turbo — consistency / editing."),
    MediaModel("runwayml/gen-3a", VIDEO, "runway", "gen3a_turbo", 50_000, "second", 10,
               "Runway Gen-3 Alpha Turbo."),
    # --- Luma (dedicated adapter) ---
    MediaModel("lumalabs/dream-machine", VIDEO, "luma", "ray-2", 320_000, "second", 9,
               "Luma Dream Machine (Ray-2)."),
    MediaModel("lumalabs/ray-flash-2", VIDEO, "luma", "ray-flash-2", 120_000, "second", 9,
               "Luma Ray Flash 2 — fast/cheap."),
    # --- MiniMax (dedicated adapter) ---
    # QM1.1 (2026-09-30): re-priced from MiniMax's pay-as-you-go page: $0.49 per
    # 1080P 6 s video (the adapter asks for 1080P) = $0.0817/s, rounded up. The
    # old 260_000 was about 3.2x the vendor cost.
    MediaModel("minimax/hailuo-02", VIDEO, "minimax", "hailuo-02", 81_700, "second", 6,
               "Hailuo 02 at 1080P — cost-effective.",
               price_source="https://platform.minimax.io/docs/guides/pricing-paygo",
               price_date="2026-09-30", price_verified=True, resolution="1080p"),
    MediaModel("minimax/hailuo-live", VIDEO, "minimax", "hailuo-live", 300_000, "second", 6,
               "Hailuo I2V-01-live — expressive motion."),
    # --- Wan / Replicate (direct owner/name paths) ---
    MediaModel("wan/wan-2.2", VIDEO, "wan", "wan22-t2v", 60_000, "second", 5,
               "Wan 2.2 — open weights (Replicate self-host tier)."),
    MediaModel("wan/wan-2.2-i2v", VIDEO, "wan", "wan22-i2v", 60_000, "second", 5,
               "Wan 2.2 image-to-video (Replicate)."),
    MediaModel("tencent/hunyuan-video-replicate", VIDEO, "wan", "tencent/hunyuan-video",
               180_000, "second", 6, "HunyuanVideo on Replicate."),
    MediaModel("lightricks/ltx-video-replicate", VIDEO, "wan", "lightricks/ltx-video",
               90_000, "second", 8, "LTX-Video on Replicate."),
    # --- HeyGen (dedicated adapter) — talking-head avatar, billed per second ---
    # Avatar is served under the video modality (poll-to-complete, video output).
    # ``model_ref`` is the HeyGen avatar/template id; owner-gated on HEYGEN_API_KEY.
    MediaModel("heygen/avatar", VIDEO, "heygen", "Daisy-inskirt-20220818", 300_000, "second", 300,
               "HeyGen talking-head avatar — script → avatar video (per second)."),
]

# --------------------------------------------------------------------------- #
# Image models (return directly)
# --------------------------------------------------------------------------- #
_IMAGE: list[MediaModel] = [
    # --- fal.ai image models (direct fal paths) ---
    # QM1.1 (2026-09-30): the label said 4.5 but the path was v4; it now calls v4.5 ($0.04 per image).
    MediaModel("bytedance-seed/seedream-4.5", IMAGE, "fal-image", "fal-ai/bytedance/seedream/v4.5/text-to-image",
               40_000, "image", description="Seedream 4.5 — high-fidelity.",
               price_source="https://fal.ai/models/fal-ai/bytedance/seedream/v4.5/text-to-image",
               price_date="2026-09-30", price_verified=True),
    # Very ___ Time (2026-10-05): Seedream 4.5 edit takes up to 10 reference images
    # (``image_urls``, last 10 used); $0.04 per image read from the fal page.
    MediaModel("bytedance-seed/seedream-4.5-edit", IMAGE, "fal-image", "fal-ai/bytedance/seedream/v4.5/edit",
               40_000, "image", description="Seedream 4.5 edit — stills conditioned on role-tagged reference images.",
               price_source="https://fal.ai/models/fal-ai/bytedance/seedream/v4.5/edit",
               price_date="2026-10-05", price_verified=True, inputs=("prompt", "images")),
    MediaModel("black-forest-labs/flux-1.1-pro", IMAGE, "fal-image", "fal-ai/flux-pro/v1.1", 40_000, "image",
               description="FLUX 1.1 Pro."),
    MediaModel("black-forest-labs/flux-1.1-pro-ultra", IMAGE, "fal-image", "fal-ai/flux-pro/v1.1-ultra",
               60_000, "image", description="FLUX 1.1 Pro Ultra — up to 4MP."),
    MediaModel("black-forest-labs/flux-schnell", IMAGE, "fal-image", "fal-ai/flux/schnell", 3_000, "image",
               description="FLUX schnell — fast/cheap (Apache)."),
    MediaModel("black-forest-labs/flux-dev", IMAGE, "fal-image", "fal-ai/flux/dev", 25_000, "image",
               description="FLUX dev — non-commercial weights (research)."),
    MediaModel("black-forest-labs/flux-krea", IMAGE, "fal-image", "fal-ai/flux/krea", 30_000, "image",
               description="FLUX Krea — aesthetic tuned."),
    MediaModel("stabilityai/sd-3.5-large", IMAGE, "fal-image", "fal-ai/stable-diffusion-v35-large", 35_000, "image",
               description="SD 3.5 Large."),
    MediaModel("google/imagen-4", IMAGE, "fal-image", "fal-ai/imagen4/preview", 40_000, "image",
               description="Imagen 4 (via fal)."),
    MediaModel("recraft/recraft-v3", IMAGE, "fal-image", "fal-ai/recraft-v3", 40_000, "image",
               description="Recraft v3 — design/vector."),
    MediaModel("ideogram/ideogram-v3", IMAGE, "fal-image", "fal-ai/ideogram/v3", 45_000, "image",
               description="Ideogram v3 — strong text rendering."),
    MediaModel("fal/aura-flow", IMAGE, "fal-image", "fal-ai/aura-flow", 20_000, "image",
               description="AuraFlow — open flow model."),
    MediaModel("nvidia/sana", IMAGE, "fal-image", "fal-ai/sana", 5_000, "image",
               description="Sana — fast efficient synthesis."),
    MediaModel("kwai/kolors", IMAGE, "fal-image", "fal-ai/kolors", 15_000, "image",
               description="Kolors — bilingual photorealism."),
    MediaModel("shitao/omnigen-v2", IMAGE, "fal-image", "fal-ai/omnigen-v2", 30_000, "image",
               description="OmniGen v2 — unified gen/edit."),
    MediaModel("hidream/hidream-i1", IMAGE, "fal-image", "fal-ai/hidream-i1-full", 40_000, "image",
               description="HiDream-I1 — open 17B."),
    MediaModel("lumalabs/photon", IMAGE, "fal-image", "fal-ai/luma-photon", 20_000, "image",
               description="Luma Photon — high aesthetic."),
    MediaModel("playground/playground-v2.5", IMAGE, "fal-image", "fal-ai/playground-v25", 20_000, "image",
               description="Playground v2.5."),
    # MH0 refresh: $0.02 per megapixel, rounded up; the default 1024x768 image is 1 MP.
    MediaModel("qwen/qwen-image", IMAGE, "fal-image", "fal-ai/qwen-image", 20_000, "image",
               description="Qwen-Image — strong text/layout (1 MP default size).",
               price_source="https://fal.ai/models/fal-ai/qwen-image",
               price_date="2026-09-29", price_verified=True),
    MediaModel("stabilityai/sdxl-fast", IMAGE, "fal-image", "fal-ai/fast-sdxl", 5_000, "image",
               description="Fast SDXL (fal)."),
    # --- MH0 current generation images (fal.ai; prices read 2026-09-29) ---
    MediaModel("bytedance/seedream-v4", IMAGE, "fal-image", "fal-ai/bytedance/seedream/v4/text-to-image",
               30_000, "image", description="Seedream V4 text-to-image.",
               price_source="https://fal.ai/models/fal-ai/bytedance/seedream/v4/text-to-image",
               price_date="2026-09-29", price_verified=True),
    MediaModel("black-forest-labs/flux-kontext-pro", IMAGE, "fal-image",
               "fal-ai/flux-pro/kontext/text-to-image", 40_000, "image",
               description="FLUX.1 Kontext [pro] — BFL API, commercial terms.",
               price_source="https://fal.ai/models/fal-ai/flux-pro/kontext/text-to-image",
               price_date="2026-09-29", price_verified=True),
    # --- OpenAI images (dedicated adapter) ---
    # 2026-09 audit: gpt-image-1 base cost $0.04 ≈ 1024² "medium" quality; it is
    # token-billed ($0.011 low → ~$0.25 high quality).
    # QM1.1 (2026-09-30), from https://developers.openai.com/api/docs/deprecations:
    # gpt-image-1 shuts down 2026-10-23 (replacement gpt-image-2.5-flare or
    # -sunburst); dall-e-2 and dall-e-3 were shut down 2026-05-12. The rows stay
    # in the catalogue history (never deleted) but are hidden from routing:
    # gpt-image-1 falls over to the successor FALLOVER_LEAD_DAYS before its end,
    # and a request for a DALL-E id answers 410 naming the successor.
    MediaModel("openai/gpt-image-1", IMAGE, "openai-image", "gpt-image-1", 40_000, "image",
               description="OpenAI gpt-image-1 — strong prompt adherence / text (ends 2026-10-23).",
               retired_on="2026-10-23", successor="openai/gpt-image-2.5-flare", fallover=True),
    MediaModel("openai/dall-e-3", IMAGE, "openai-image", "dall-e-3", 40_000, "image",
               description="OpenAI DALL·E 3 — shut down 2026-05-12 (historical price).",
               retired_on="2026-05-12", successor="openai/gpt-image-2.5-flare"),
    MediaModel("openai/dall-e-2", IMAGE, "openai-image", "dall-e-2", 16_000, "image",
               description="OpenAI DALL·E 2 — shut down 2026-05-12 (historical price).",
               retired_on="2026-05-12", successor="openai/gpt-image-2.5-flare"),
    # QM1.1 successor, via fal (the fal adapter sends only the prompt, so fal's
    # defaults apply: quality "high", landscape 4:3). Priced at fal's high
    # quality 1024x1024 rate, $0.05268, which covers the default size.
    # OpenAI's own page lists $30 per 1M image output tokens for this model.
    MediaModel("openai/gpt-image-2.5-flare", IMAGE, "fal-image", "openai/gpt-image-2.5/flare/text-to-image",
               52_680, "image", description="GPT Image 2.5 Flare — fast, strong prompt adherence and text.",
               price_source="https://fal.ai/models/openai/gpt-image-2.5/flare/text-to-image",
               price_date="2026-09-30", price_verified=True),
    # --- Google Nano Banana (Gemini image models, via fal) ---
    # QM1.1 (2026-09-30), from https://ai.google.dev/gemini-api/docs/pricing:
    # gemini-2.5-flash-image ("Nano Banana") is deprecated and shuts down
    # 2026-10-02, so its row falls over to Nano Banana 2 (gemini-3.1-flash-image).
    MediaModel("google/nano-banana", IMAGE, "fal-image", "fal-ai/nano-banana", 39_000, "image",
               description="Nano Banana (Gemini 2.5 Flash Image) — image generation and editing (ends 2026-10-02).",
               price_source="https://fal.ai/models/fal-ai/nano-banana",
               price_date="2026-09-30", price_verified=True,
               retired_on="2026-10-02", successor="google/nano-banana-2", fallover=True),
    MediaModel("google/nano-banana-2", IMAGE, "fal-image", "fal-ai/nano-banana-2", 80_000, "image",
               description="Nano Banana 2 (Gemini 3.1 Flash Image) at 1K — versatile generation and editing.",
               price_source="https://fal.ai/models/fal-ai/nano-banana-2",
               price_date="2026-09-30", price_verified=True),
    # --- Google Imagen (dedicated adapter, sync predict) ---
    MediaModel("google/imagen-4-generate", IMAGE, "imagen", "imagen-4.0-generate-001", 40_000, "image",
               description="Imagen 4 (Google API)."),
    MediaModel("google/imagen-4-fast", IMAGE, "imagen", "imagen-4.0-fast-generate-001", 20_000, "image",
               description="Imagen 4 Fast (Google) — base64/data-url output."),
    MediaModel("google/imagen-3", IMAGE, "imagen", "imagen-3.0-generate-002", 40_000, "image",
               description="Imagen 3 (Google) — high fidelity."),
    # --- Replicate image models (direct owner/name paths) ---
    MediaModel("black-forest-labs/flux-schnell-replicate", IMAGE, "replicate-image",
               "black-forest-labs/flux-schnell", 3_000, "image",
               description="FLUX schnell on Replicate — fast/cheap (Apache weights)."),
    MediaModel("black-forest-labs/flux-1.1-pro-replicate", IMAGE, "replicate-image",
               "black-forest-labs/flux-1.1-pro", 40_000, "image",
               description="FLUX 1.1 Pro on Replicate."),
    MediaModel("stability-ai/sdxl", IMAGE, "replicate-image", "stability-ai/sdxl", 12_000, "image",
               description="SDXL on Replicate — OpenRAIL++ weights."),
    MediaModel("stability-ai/sd-3.5-large-replicate", IMAGE, "replicate-image",
               "stability-ai/stable-diffusion-3.5-large", 35_000, "image",
               description="SD 3.5 Large on Replicate."),
    MediaModel("ideogram-ai/ideogram-v3-turbo", IMAGE, "replicate-image",
               "ideogram-ai/ideogram-v3-turbo", 30_000, "image",
               description="Ideogram v3 Turbo on Replicate."),
    MediaModel("recraft-ai/recraft-v3-replicate", IMAGE, "replicate-image", "recraft-ai/recraft-v3",
               40_000, "image", description="Recraft v3 on Replicate."),
    MediaModel("playgroundai/playground-v2.5", IMAGE, "replicate-image",
               "playgroundai/playground-v2.5-1024px-aesthetic", 15_000, "image",
               description="Playground v2.5 on Replicate."),
]

# --------------------------------------------------------------------------- #
# Audio models (poll-to-complete, flat per-generation price)
# --------------------------------------------------------------------------- #
_AUDIO: list[MediaModel] = [
    MediaModel("suno/v4", AUDIO, "suno", "suno-v4", 80_000, "clip",
               description="Suno v4 — full song with vocals."),
    MediaModel("suno/v4.5", AUDIO, "suno", "suno-v4.5", 100_000, "clip",
               description="Suno v4.5 — richer arrangements / longer."),
    MediaModel("suno/v3.5", AUDIO, "suno", "suno-v3.5", 60_000, "clip",
               description="Suno v3.5 — fast/cheap."),
    # --- Voice (text-to-speech) — synchronous, flat per-clip price ---
    # ``model_ref`` is the TTS model/quality tier; the request's ``voice_id`` picks
    # the actual voice. Owner-gated on ELEVENLABS_API_KEY; byte output is hosted to
    # R2 → presigned https URL by the adapter (data: URLs are image-only).
    MediaModel("elevenlabs/multilingual-v2", AUDIO, "elevenlabs", "eleven_multilingual_v2",
               30_000, "clip", description="ElevenLabs multilingual v2 — natural TTS voice."),
    MediaModel("elevenlabs/turbo-v2.5", AUDIO, "elevenlabs", "eleven_turbo_v2_5",
               18_000, "clip", description="ElevenLabs Turbo v2.5 — low-latency TTS."),
    # Self-hosted / free fallbacks share the ``tts`` adapter (base URL + optional
    # key injected per deployment: TTS_BASE_URL / TTS_API_KEY).
    MediaModel("tts/kokoro", AUDIO, "tts", "kokoro", 2_000, "clip",
               description="Kokoro (Apache) — self-hosted TTS fallback."),
    MediaModel("tts/chatterbox", AUDIO, "tts", "chatterbox", 2_000, "clip",
               description="Chatterbox (MIT) — self-hosted TTS fallback."),
]

# --------------------------------------------------------------------------- #
# Stage models (MH0): need audio/video inputs, so not on the prompt-only gateway
# --------------------------------------------------------------------------- #
_STAGE: list[MediaModel] = [
    # $3 per minute of output video (lipsync-2-pro is $5/min).
    MediaModel("sync/lipsync-2", VIDEO, "kling-fal", "fal-ai/sync-lipsync/v2", 50_000, "second", 300,
               "sync lipsync-2 — re-sync an existing video to new audio ($3/min).",
               price_source="https://fal.ai/models/fal-ai/sync-lipsync/v2",
               price_date="2026-09-29", price_verified=True, inputs=("video", "audio")),
    # $0.20/s at 480p; the price doubles at 720p.
    MediaModel("meigen/infinitetalk", VIDEO, "kling-fal", "fal-ai/infinitalk", 200_000, "second", 60,
               "InfiniteTalk — premium talking avatar from one image and audio (480p).",
               price_source="https://fal.ai/models/fal-ai/infinitalk",
               price_date="2026-09-29", price_verified=True, resolution="480p",
               inputs=("image", "audio")),
    # $0.001 per megapixel of video (width x height x frames); 1080p x 121 frames is about $0.25.
    MediaModel("bytedance/seedvr2-upscale", VIDEO, "kling-fal", "fal-ai/seedvr/upscale/video",
               1_000, "megapixel", 0,
               "SeedVR2 video upscale (Apache-2.0 weights), billed per output megapixel.",
               price_source="https://fal.ai/models/fal-ai/seedvr/upscale/video",
               price_date="2026-09-29", price_verified=True, inputs=("video",)),
]

# --------------------------------------------------------------------------- #
# Legacy relabel (MH0): pre-MH0 rows keep routing, gain a source, say "Legacy:"
# --------------------------------------------------------------------------- #
LEGACY_SOURCE_DATE = "2026-09-29"
_KLING_ALIAS_PATHS = {
    "kling-t2v": "fal-ai/kling-video/v1.6/standard/text-to-video",
    "kling-i2v": "fal-ai/kling-video/v1.6/standard/image-to-video",
    "kling-pro-t2v": "fal-ai/kling-video/v2/master/text-to-video",
    "kling-pro-i2v": "fal-ai/kling-video/v2/master/image-to-video",
}
_VENDOR_PRICE_PAGES = {
    "veo": "https://ai.google.dev/gemini-api/docs/pricing",
    "imagen": "https://ai.google.dev/gemini-api/docs/pricing",
    "runway": "https://docs.dev.runwayml.com/guides/pricing/",
    "luma": "https://lumalabs.ai/api/pricing",
    "minimax": "https://www.minimax.io/price",
    "heygen": "https://www.heygen.com/api-pricing",
    "openai-image": "https://platform.openai.com/docs/pricing",
    "suno": "https://suno.com/pricing",
    "elevenlabs": "https://elevenlabs.io/pricing/api",
    "tts": "internal:self-hosted-tts-compute",
}


def legacy_price_source(m: MediaModel) -> str:
    """Where a pre-MH0 row's price is checked (fal/Replicate model page or vendor page)."""
    if m.provider in ("kling-fal", "fal-image"):
        path = _KLING_ALIAS_PATHS.get(m.model_ref, m.model_ref)
        return f"https://fal.ai/models/{path}"
    if m.provider in ("wan", "replicate-image"):
        ref = m.model_ref
        return f"https://replicate.com/{ref}" if "/" in ref else "https://replicate.com/pricing"
    return _VENDOR_PRICE_PAGES.get(m.provider, "")


def _as_legacy(m: MediaModel) -> MediaModel:
    if m.price_verified:
        return m
    desc = m.description if m.description.startswith("Legacy:") else f"Legacy: {m.description}"
    return replace(
        m,
        legacy=True,
        description=desc,
        price_source=m.price_source or legacy_price_source(m),
        price_date=m.price_date or LEGACY_SOURCE_DATE,
    )


_VIDEO = [_as_legacy(m) for m in _VIDEO]
_IMAGE = [_as_legacy(m) for m in _IMAGE]
_AUDIO = [_as_legacy(m) for m in _AUDIO]

# --------------------------------------------------------------------------- #
# Direct ByteDance rows (BytePlus ModelArk, provider "ark"); added after the legacy
# relabel because they are new rows whose price is not yet read from a BytePlus page.
# --------------------------------------------------------------------------- #
# ModelArk bills tokens: (seconds x width x height x 24 fps) / 1024. At 720p that is
# 21,600 tokens per second; at $7.00 per 1M tokens (no video input) = $0.1512/s.
# The $7.00 rate comes from third-party write-ups of the BytePlus rate table, so
# price_verified stays False until the drift check or an owner reads it live.
ARK_PRICE_SOURCE = "https://docs.byteplus.com/en/docs/ModelArk/1544106"
_ARK_VIDEO: list[MediaModel] = [
    MediaModel("bytedance/seedance-2.0-i2v-ark", VIDEO, "ark", seedance_ark_model(), 151_200, "second", 15,
               "Seedance 2.0 image-to-video direct from BytePlus ModelArk at 720p "
               "(price unverified: from third-party copies of the BytePlus token rate).",
               price_source=ARK_PRICE_SOURCE, price_date="2026-10-05", price_verified=False,
               resolution="720p", inputs=("prompt", "image")),
    MediaModel("bytedance/seedance-2.0-r2v-ark", VIDEO, "ark", seedance_ark_model(), 151_200, "second", 15,
               "Seedance 2.0 reference-to-video direct from BytePlus ModelArk at 720p "
               "(price unverified: from third-party copies of the BytePlus token rate).",
               price_source=ARK_PRICE_SOURCE, price_date="2026-10-05", price_verified=False,
               resolution="720p", inputs=("prompt", "images")),
]
_VIDEO = [*_VIDEO, *_ARK_VIDEO]

# --------------------------------------------------------------------------- #
# Replicate rows for the Very ___ Time lanes (2026-10-05). Only REPLICATE_API_TOKEN
# may be configured, so every step needs a Replicate path. Input schemas were read
# from GET /v1/models/{owner}/{name}; Replicate's model pages show no price text to
# an unauthenticated reader, so these prices are estimates (price_verified=False)
# until the drift check or an owner reads them from the account's billing page.
# Added after the legacy relabel (like the ARK rows) so they keep their own labels.
# --------------------------------------------------------------------------- #
_REPLICATE_VIDEO: list[MediaModel] = [
    MediaModel("bytedance/seedance-2.0-i2v-replicate", VIDEO, "wan", "bytedance/seedance-2.0", 302_400, "second", 15,
               "Seedance 2.0 image-to-video on Replicate at 720p with native audio "
               "(price unverified: estimated at the fal rate).",
               price_source="https://replicate.com/bytedance/seedance-2.0", price_date="2026-10-05",
               price_verified=False, resolution="720p", inputs=("prompt", "image")),
    MediaModel("bytedance/seedance-2.0-r2v-replicate", VIDEO, "wan", "bytedance/seedance-2.0", 302_400, "second", 15,
               "Seedance 2.0 reference-to-video on Replicate at 720p with native audio, up to 4 role-tagged images "
               "(price unverified: estimated at the fal rate).",
               price_source="https://replicate.com/bytedance/seedance-2.0", price_date="2026-10-05",
               price_verified=False, resolution="720p", inputs=("prompt", "images")),
    MediaModel("bytedance/seedance-1-lite-r2v-replicate", VIDEO, "wan", "bytedance/seedance-1-lite", 36_000,
               "second", 12,
               "Seedance 1 Lite reference-to-video on Replicate at 720p, silent, 1-4 reference images "
               "(price unverified).",
               price_source="https://replicate.com/bytedance/seedance-1-lite", price_date="2026-10-05",
               price_verified=False, resolution="720p", inputs=("prompt", "images")),
    MediaModel("kwaivgi/kling-v2.1-i2v-replicate", VIDEO, "wan", "kwaivgi/kling-v2.1", 50_000, "second", 10,
               "Kling 2.1 standard image-to-video on Replicate at 720p, 5 or 10 s (price unverified).",
               price_source="https://replicate.com/kwaivgi/kling-v2.1", price_date="2026-10-05",
               price_verified=False, resolution="720p", inputs=("prompt", "image")),
]
_REPLICATE_IMAGE: list[MediaModel] = [
    MediaModel("bytedance/seedream-4.5-replicate", IMAGE, "replicate-image", "bytedance/seedream-4.5", 40_000,
               "image", description="Seedream 4.5 on Replicate: text-to-image and multi-reference edits "
               "(up to 14 images), strong lettering (price unverified).",
               price_source="https://replicate.com/bytedance/seedream-4.5", price_date="2026-10-05",
               price_verified=False, inputs=("prompt", "images")),
    # Nano Banana Pro on Replicate: the model the 2026-10-05 Oxhan episode renders used for the
    # turnaround sheet and every still (correct VERY TURKISH TIME lettering with the sheet as
    # reference). $0.15 per 2K image was billed on those runs (gtm/oxhan-very-turkish-time/
    # cost-ledger.csv); not read from a public price page, so unverified.
    MediaModel("google/nano-banana-pro-replicate", IMAGE, "replicate-image", "google/nano-banana-pro", 150_000,
               "image", description="Nano Banana Pro on Replicate at 2K: multi-reference stills with "
               "legible garment lettering (price from billed runs, unverified).",
               price_source="https://replicate.com/google/nano-banana-pro", price_date="2026-10-05",
               price_verified=False, inputs=("prompt", "images")),
    MediaModel("black-forest-labs/flux-kontext-pro-replicate", IMAGE, "replicate-image",
               "black-forest-labs/flux-kontext-pro", 40_000, "image",
               description="FLUX.1 Kontext [pro] on Replicate: one reference image edit (price unverified).",
               price_source="https://replicate.com/black-forest-labs/flux-kontext-pro", price_date="2026-10-05",
               price_verified=False, inputs=("prompt", "image")),
]
_VIDEO = [*_VIDEO, *_REPLICATE_VIDEO]
_IMAGE = [*_IMAGE, *_REPLICATE_IMAGE]

_BY_ID = {m.id: m for m in (*_VIDEO, *_IMAGE, *_AUDIO)}
_STAGE_BY_ID = {m.id: m for m in _STAGE}


def today() -> date:
    return datetime.now(timezone.utc).date()


def _ended(m: MediaModel, on: date) -> bool:
    """True when ``m`` no longer routes on ``on``: past its end, or inside the fall-over lead."""
    if not m.retired_on:
        return False
    end = date.fromisoformat(m.retired_on)
    lead = timedelta(days=FALLOVER_LEAD_DAYS if m.fallover else 0)
    return on >= end - lead


def get_row(model_id: str) -> MediaModel | None:
    """The catalogue row itself, retired or not (history, audits, old job lookups)."""
    return _BY_ID.get(str(model_id or "").strip())


def get_model(model_id: str, *, on: date | None = None) -> MediaModel | None:
    """The row to route ``model_id`` to on ``on`` (today by default).

    A row inside its fall-over window resolves to its successor; a retired row
    without fall-over resolves to ``None`` (see :func:`retired` for the reason).
    """
    m = get_row(model_id)
    moment = on or today()
    seen: set[str] = set()
    while m is not None and _ended(m, moment):
        if not m.fallover or not m.successor or m.id in seen:
            return None
        seen.add(m.id)
        m = get_row(m.successor)
    return m


def retired(model_id: str, *, on: date | None = None) -> MediaModel | None:
    """The row when it is retired on ``on`` and does not fall over (it answers 410), else ``None``."""
    m = get_row(model_id)
    if m is None or not _ended(m, on or today()) or m.fallover:
        return None
    return m


def list_models(modality: str | None = None, *, on: date | None = None) -> list[MediaModel]:
    """Routable rows (retired rows are hidden, not deleted: see :func:`history_rows`)."""
    moment = on or today()
    models = [m for m in _BY_ID.values() if not _ended(m, moment)]
    if modality:
        models = [m for m in models if m.modality == modality]
    return sorted(models, key=lambda m: (m.modality, m.price_micros))


def history_rows() -> list[MediaModel]:
    """Every gateway row ever listed, retired ones included."""
    return sorted(_BY_ID.values(), key=lambda m: (m.modality, m.price_micros))


def video_models() -> list[MediaModel]:
    return list_models(VIDEO)


def image_models() -> list[MediaModel]:
    return list_models(IMAGE)


def audio_models() -> list[MediaModel]:
    return list_models(AUDIO)


def stage_models() -> list[MediaModel]:
    """Input-driven models (lipsync, talking avatar, upscale); not on ``/media/*``."""
    return sorted(_STAGE, key=lambda m: m.price_micros)


def get_stage_model(model_id: str) -> MediaModel | None:
    return _STAGE_BY_ID.get(str(model_id or "").strip())


def all_rows() -> list[MediaModel]:
    """Every priced row (gateway and stage), for the drift check and the licence matrix."""
    return [*list_models(), *stage_models()]


def current_models(modality: str | None = None) -> list[MediaModel]:
    """Rows whose price was verified at the source (the non-legacy catalog)."""
    return [m for m in list_models(modality) if not m.legacy]
