# Third-party models: licence register

Owner: MO1 (Wave D, 2026-09-29). Source of truth in code:
`apps/api/app/domains/routing/license_class.py` (route, gateway and catalog gate)
and `apps/api/app/domains/speak/licensing.py` (lipsync gate).
`apps/api/tests/licensing/test_paid_gate_matrix.py` fails if a key in the code
table is missing from this page, or if a gateway or catalog row has no licence.

## Rule

A paying customer's output never uses non-commercial, research-only or
unreviewed weights. The gate fails closed:

- A public model id with no recorded licence is not sellable.
- The media gateway answers 403 for a blocked model before any wallet hold or
  provider call. `GET /media/models` keeps every row and adds `license_class`
  and `sellable`.
- The reviewed catalog refuses live promotion of a blocked model (for example
  `meta/musicgen-large`), even with a price and an adapter.
- The paid presenter stage and its pre-debit check refuse a blocked presenter
  (LatentSync until MO12b).
- The speak lipsync gate (`speak/licensing.py`) keeps `musetalk` as the only
  commercial lipsync provider. `latentsync` is `non_commercial` there too.
- Free and research paths keep every model. Nothing is removed from the tree.

Classes: `permissive` and `commercial_api` and `restricted` may be sold
(`restricted` can carry conditions such as a revenue cap or attribution).
`non_commercial`, `research_only` and `unreviewed` may not.

## How to change a row

1. Record the licence with a source URL and the date you read it (MH0 adds a
   price source to each catalog row the same way).
2. Edit the row in `license_class.py` (and `speak/licensing.py` for lipsync).
3. Update the table below and run
   `pytest apps/api/tests/licensing`.
4. `latentsync` returns to a paid class only when the MO12b fork (MediaPipe
   face detection, no InsightFace) ships in the worker image.

## Register

Paid = may back a paid output. Attribution: keep the upstream licence notice
with any self-hosted weights or code we ship; hosted APIs follow the vendor's
terms.

| Key | Class | Paid | Licence and notes |
|---|---|---|---|
| `aiva` | commercial_api | yes | hosted API, vendor terms. |
| `anthropic` | commercial_api | yes | hosted API, vendor terms. |
| `bfl_api` | commercial_api | yes | FLUX 1.1 [pro] / [pro] ultra: BFL API terms, commercial OK. |
| `bytedance` | commercial_api | yes | Seedance / Seedream hosted API. |
| `cartesia` | commercial_api | yes | hosted API, vendor terms. |
| `did` | commercial_api | yes | hosted API, vendor terms. |
| `elevenlabs` | commercial_api | yes | hosted API, vendor terms. |
| `google` | commercial_api | yes | Gemini / Imagen / Veo via Google's API. |
| `heygen` | commercial_api | yes | hosted API, vendor terms. |
| `higgsfield` | commercial_api | yes | Higgsfield DoP hosted API: commercial terms, paid-safe. |
| `ideogram` | commercial_api | yes | hosted API, vendor terms. |
| `kling` | commercial_api | yes | hosted API, vendor terms. |
| `luma` | commercial_api | yes | hosted API, vendor terms. |
| `minimax` | commercial_api | yes | Hailuo / speech hosted API. |
| `openai` | commercial_api | yes | hosted API, vendor terms. |
| `openrouter` | commercial_api | yes | hosted LLM text routes via OpenRouter. |
| `pika` | commercial_api | yes | hosted API, vendor terms. |
| `pixverse` | commercial_api | yes | hosted API, vendor terms. |
| `playht` | commercial_api | yes | hosted API, vendor terms. |
| `recraft` | commercial_api | yes | hosted API, vendor terms. |
| `runway` | commercial_api | yes | hosted API, vendor terms. |
| `seedance` | commercial_api | yes | hosted API, vendor terms. |
| `sora2` | commercial_api | yes | OpenAI Sora 2 API removal: migrate to routed Veo/Kling/Seedance. Sunset 2026-09-24; replacement `veo`. |
| `gpt_image_1` | commercial_api | yes | OpenAI gpt-image-1. Sunset 2026-10-23; routing falls over to `openai/gpt-image-2.5-flare` 3 days before (QM1.1). |
| `dall_e` | commercial_api | yes | OpenAI DALL-E 2 and 3, shut down 2026-05-12. Rows kept in history, hidden from routing; the gateway answers 410 naming `openai/gpt-image-2.5-flare`. |
| `gpt_image_25` | commercial_api | yes | OpenAI GPT Image 2.5 Flare via fal, vendor terms. Source https://developers.openai.com/api/docs/deprecations read 2026-09-30. |
| `nano_banana` | commercial_api | yes | Gemini 2.5 Flash Image (Nano Banana) via fal. Sunset 2026-10-02; falls over to `google/nano-banana-2`. |
| `nano_banana_pro` | commercial_api | yes | Gemini 3 Pro Image (Nano Banana Pro) via Replicate, Google API terms. |
| `nano_banana_2` | commercial_api | yes | Gemini 3.1 Flash Image (Nano Banana 2) via fal, Google API terms. Source https://ai.google.dev/gemini-api/docs/pricing read 2026-09-30. |
| `stable_audio_api` | commercial_api | yes | Stable Audio 2.5 through Stability AI's hosted API (official Replicate model), vendor terms. Source https://replicate.com/stability-ai/stable-audio-2.5 read 2026-10-05. |
| `suno` | commercial_api | yes | hosted API, vendor terms. |
| `udio` | commercial_api | yes | hosted API, vendor terms. |
| `veo` | commercial_api | yes | hosted API, vendor terms. |
| `f5_tts` | non_commercial | no | F5-TTS weights: CC-BY-NC-4.0. |
| `flux2_klein_9b` | non_commercial | no | FLUX.2 [klein] 9B: FLUX Non-Commercial License. |
| `flux_dev` | non_commercial | no | FLUX.1 [dev] Non-Commercial License. |
| `flux_krea` | non_commercial | no | FLUX.1 Krea [dev]: same FLUX.1 [dev] Non-Commercial License. |
| `hunyuanvideo` | non_commercial | no | Tencent HunyuanVideo: non-commercial terms + EU/UK/KR territorial exclusion; reference-only for global. |
| `latentsync` | non_commercial | no | InsightFace dependency (non-commercial models); paid use waits for the MO12b MediaPipe fork. |
| `liveportrait` | non_commercial | no | LivePortrait uses InsightFace (non-commercial models). |
| `mmaudio` | non_commercial | no | MMAudio weights: CC-BY-NC-4.0. |
| `musicgen` | non_commercial | no | Meta MusicGen weights: CC-BY-NC-4.0. |
| `rmbg2` | non_commercial | no | BRIA RMBG-2.0 weights: CC-BY-NC-4.0. |
| `xtts` | non_commercial | no | Coqui CPML: non-commercial. |
| `ace_step` | permissive | yes | ACE-Step 1.5: MIT; replaces MusicGen. |
| `auraflow` | permissive | yes | AuraFlow: Apache-2.0. |
| `chatterbox` | permissive | yes | MIT: commercial OK. |
| `flux2_klein_4b` | permissive | yes | FLUX.2 [klein] 4B: Apache-2.0. |
| `flux_schnell` | permissive | yes | FLUX.1 [schnell]: Apache-2.0. |
| `hidream` | permissive | yes | HiDream-I1: MIT. |
| `kokoro` | permissive | yes | Apache-2.0: commercial OK. |
| `omnigen2` | permissive | yes | OmniGen2: Apache-2.0. |
| `qwen_image` | permissive | yes | Qwen-Image: Apache-2.0. |
| `rembg` | permissive | yes | rembg + BiRefNet: MIT. |
| `z_image` | permissive | yes | Z-Image: Apache-2.0. |
| `wav2lip` | research_only | no | Wav2Lip: research / non-commercial use only. |
| `animatediff` | restricted | yes | AnimateDiff: Apache-2.0 motion module; SD1.5 base (CreativeML OpenRAIL-M). |
| `cogvideox` | restricted | yes | CogVideoX-2B Apache-2.0; 5B under the CogVideoX License (commercial with registration). |
| `ltx` | restricted | yes | LTX-Video open weights licence: commercial OK with conditions. |
| `mochi` | restricted | yes | Mochi-1 (Genmo): Apache-2.0 open weights, commercial OK. |
| `musetalk` | restricted | yes | MuseTalk 1.5: MIT code and weights. |
| `playground` | restricted | yes | Playground v2.5 Community License: commercial OK with conditions. |
| `stability` | restricted | yes | SDXL / SD 3.5: Stability AI Community License, commercial OK under revenue cap. |
| `svd` | restricted | yes | Stable Video Diffusion: Stability AI Community License, commercial OK under revenue cap. |
| `wan22` | restricted | yes | Apache-2.0 weights: commercial OK. |
| `wan_camera` | restricted | yes | Wan2.2-Fun-A14B camera control: open weights (Apache-2.0), commercial OK. |
| `edge_tts` | unreviewed | no | Edge read-aloud endpoint (unofficial); kept as the free fallback voice, not a sold catalog SKU. |
| `flux` | unreviewed | no | ambiguous family key; use flux_schnell, flux_dev or bfl_api. |
| `kolors` | unreviewed | no | Kolors: weights need Kuaishou commercial registration. |
| `sadtalker` | unreviewed | no | SadTalker: face-enhancer weights to review. |
| `sana` | restricted | yes | NVIDIA Sana 1600M: Apache-2.0 weights; the Gemma-2 text encoder follows the Gemma Terms and Prohibited Use Policy (MH0, source read 2026-09-29). |
| `ltx2` | restricted | yes | LTX-2 Community License: commercial use only below $10M annual revenue (OD9). Re-check before revenue crosses the cap. Source https://github.com/Lightricks/LTX-2 (MH0, 2026-09-29). |
| `infinitetalk` | permissive | yes | MeiGen InfiniteTalk: Apache-2.0 on Wan2.1-14B weights. Source https://github.com/MeiGen-AI/InfiniteTalk (MH0, 2026-09-29). |
| `seedvr2` | permissive | yes | ByteDance SeedVR2 video upscale: Apache-2.0 weights (MH0, 2026-09-29). |
| `sync` | commercial_api | yes | sync. lipsync-2 hosted API via fal, vendor terms (MH0). |
| `wan25` | commercial_api | yes | Alibaba Wan 2.5 preview: hosted API only, no open weights (MH0). |

## Lipsync providers (`speak/licensing.py`)

| Provider | Class | Paid |
|---|---|---|
| `musetalk` | open_commercial | yes |
| `latentsync` | non_commercial (until MO12b) | no |
| `wav2lip` | research_only | no |

## Open items

- `kolors`, `sadtalker`, `edge_tts` and the bare `flux` family key stay
  `unreviewed` after MH0: Kolors needs a Kuaishou commercial registration we
  have not made, SadTalker's face-enhancer weights are still unreviewed, and
  edge-tts is the free fallback voice, not a sold SKU. They stay blocked for
  paid and keep running on free paths.
- MH0 (2026-09-29) added `ltx2`, `infinitetalk`, `seedvr2`, `sync` and `wan25`
  and moved `sana` to `restricted` with a source. Catalog price sources live in
  `media_catalog.py` (`price_source`, `price_date`) and the weekly drift check
  is `app/services/loops/price_drift.py`.
