# ReelForge External Project Registry

> **Purpose:** Governance record for source checked out under `external/`.
> Presence here does not mean the project is part of ReelForge's runtime or that
> its model weights are approved for commercial use.
>
> **Legal note:** License labels below are an engineering inventory from the
> checked-out files, not legal advice. Software, custom nodes, model weights,
> datasets, and generated-output terms must be reviewed separately.

## 0. Product lineage (upstream foundations, not `external/` references)

ReelForge is not greenfield; two permissively-licensed projects are its trunk and
are recorded here for **attribution + license provenance**, though their code ships
inside `apps/*` rather than sitting under `external/`:

- **MoneyPrinterTurbo** (`harry0703/MoneyPrinterTurbo`, MIT) — the origin of the
  **`apps/api` backend**: the FastAPI service, the `controllers/v1/{video,voice,music,subtitle}`
  surface, the script → TTS → subtitle → compose pipeline, and much of `app/services/*`
  descend from it. ReelForge extended it into the wallet/gateway/reels product;
  the MPT legacy `/videos`/`/audio` routes are why the media gateway is namespaced
  under `/media/*` (see [ADR 0003](../adr/0003-media-gateway-namespacing.md)).
- **OpenCut** (`OpenCut-app/OpenCut`, MIT) — the origin of the **timeline editor**;
  see its row in §2 (`ported-source`). Preserved source lives in
  `apps/web/editor-module`; the active editor is `apps/web/src/features/editor`,
  extended to mobile (`app/editor.tsx`) and desktop (`rf-project::timeline`).

Both are MIT, so porting into product source is permitted; keep their `LICENSE`
attribution intact in the ported trees — the root [`LICENSE`](../LICENSE) is
MoneyPrinterTurbo's, and [`apps/web/editor-module/LICENSE`](../apps/web/editor-module/LICENSE)
is OpenCut's, both retained verbatim. The consolidated attribution record is
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) at the repo root.

## 1. Adoption states

| State | Meaning |
|---|---|
| `reference` | Read-only research; no runtime or copied product code |
| `candidate` | Technically relevant; requires architecture, license, security, and operations review |
| `adapter-active` | Product talks to a separately deployed service through a product-owned adapter |
| `isolated-runtime` | Approved pinned source runs in its own image/service boundary |
| `ported-source` | A permissively-licensed project forked/ported **into** product source (`apps/*`); attribution + license origin recorded here, but the code now lives and ships in the product |
| `rejected-runtime` | May inform research but must not enter the production dependency graph |

## 2. Registry

| Project | Upstream | Checked commit | Checked software license | Current state | ReelForge relevance |
|---|---|---:|---|---|---|
| ComfyUI | `comfyanonymous/ComfyUI` | `8f37cf8` | GPL-3.0 in checked `LICENSE` | `candidate` | Workflow execution engine for image/video/audio graphs |
| comfyui-deploy | `BennyKok/comfyui-deploy` | `98c1aca` | AGPL-3.0 | `adapter-active` | Existing B-roll adapter calls its separately deployed HTTP control plane |
| Wan2.2 | `Wan-Video/Wan2.2` | `42bf4cf` | Apache-2.0 in checked repo; model/use conditions still reviewed separately | `candidate` | Preferred open model family for T2V/I2V B-roll evaluation |
| Wan2GP | `deepbeepmeep/Wan2GP` | `89a77e3` | WanGP Community License 2.0 plus component licenses | `reference` | Low-VRAM inference, quantization, post-processing, API ideas |
| VideoTuna | `VideoVerses/VideoTuna` | `acf95b6` | CC-BY-NC-ND per checked README/LICENSE | `rejected-runtime` | Multi-model training and evaluation research only; non-commercial/no-derivatives terms conflict with direct product integration |
| VideoX-Fun | `aigc-apps/VideoX-Fun` | `6787dc8` | Apache-2.0 for repository; individual models vary | `reference` | Training/inference patterns and model comparison |
| ViewComfy | `ViewComfy/ViewComfy` | `fc0ba28` | AGPL-3.0 | `reference` | Workflow-to-app UX and hosting research; duplicates ReelForge client/product responsibilities |
| hyvideo | local source snapshot; no origin recorded in this checkout | `08ed1d8` | not established from a top-level license in the checked snapshot | `rejected-runtime` | Hunyuan inference implementation reference until provenance and license are resolved |
| OpenCut | `OpenCut-app/OpenCut` | ported into `apps/web/{editor-module,editor-bff,src/features/editor}`; ported base commit unrecorded (upstream HEAD `400f097` @2026-08-01) | MIT (permits porting into product source) | `ported-source` | The non-destructive timeline editor foundation ReelForge's editor is built on — preserved OpenCut source in `apps/web/editor-module`, its Elysia worker retained as the stateless `apps/web/editor-bff` transport seam, and the active product editor in `apps/web/src/features/editor`; the same timeline model extends to mobile (`app/editor.tsx`) and desktop (`rf-project::timeline`) |
| Pixelle-Video | `AIDC-AI/Pixelle-Video` | not cloned; upstream HEAD `848b054` @2026-06-14 (pin at fetch) | Apache-2.0 per GitHub API — confirm at fetch | `candidate` | ComfyUI/MCP-based media engine; §7.3 tracks it as a separately benchmarked B-roll provider option |
| SwarmUI | `mcmonkeyprojects/SwarmUI` | not cloned; upstream HEAD `909e526` @2026-08-18 (pin at fetch) | MIT per GitHub API — confirm at fetch | `reference` | ComfyUI orchestration/queue + model-management UX research (admin-side only; not a first-party client) |
| FramePack | `lllyasviel/FramePack` | not cloned; upstream HEAD `97fe5db` @2025-10-16 (pin at fetch) | Apache-2.0 (code); weights vary — confirm at fetch | `reference` | Efficient long-form I2V (frame-context packing); benchmark candidate behind the ComfyUI B-roll adapter like AnimateDiff, with per-weight license gating |
| OBrainRot | `harvestingmoon/OBrainRot` | not yet cloned | MIT per GitHub API; top-level `LICENSE` SPDX unresolved — confirm at fetch | `reference` | Faceless-pipeline mechanics: Coqui xTTSv2 TTS → wav2vec2 forced alignment → ffmpeg caption sync |
| FullyAutomatedRedditVideoMakerBot | `raga70/FullyAutomatedRedditVideoMakerBot` | not yet cloned | GPL-3.0 | `reference` | Distribution patterns: ElevenLabs key-rotation at scale, Playwright TikTok/IG/YT uploader (ToS-risk; see §7) |
| RedditVideoMakerBot | `elebumm/RedditVideoMakerBot` | not yet cloned | GPL-3.0 | `reference` | Canonical faceless prior art: script → TTS → caption → background → ffmpeg compose |
| brainrot-generator | `egebese/brainrot-generator` | not yet cloned | license unconfirmed — confirm at fetch | `reference` | Config layout for swappable background/voice/music + web-UI picker patterns |
| Open-Higgsfield-AI | `ClabstreamTeam/Open-Higgsfield-AI` | not yet cloned | NOASSERTION — confirm at fetch | `reference` | UI/UX reference for the unified media gateway: one key → 40+ T2V, 60+ I2V, 9 lipsync models behind one studio |
| AnimateDiff | `guoyww/AnimateDiff` | not yet cloned | Apache-2.0 (code); motion-module weights vary | `reference` | Open motion-module animation / I2V; evaluate via ComfyUI behind the B-roll adapter |
| generative-models (SVD) | `Stability-AI/generative-models` | not yet cloned | MIT (code); SVD weights under **Stability Non-Commercial** research license | `rejected-runtime` | Stable Video Diffusion I2V reference; weights are non-commercial → no product runtime |
| Layer AI | provenance unresolved (no confirmed upstream URL) | not yet cloned | unknown | `rejected-runtime` | Node-based generation-workflow UX idea; resolve URL + license before any evaluation |
| candle | `huggingface/candle` | vendored snapshot at enclosing repository commit `9cedc271` | MIT OR Apache-2.0 | `candidate` | Rust ML framework retained for local-inference evaluation; not linked into the product workspace |
| mistral.rs | `EricLBuehler/mistral.rs` | vendored snapshot at enclosing repository commit `9cedc271` | MIT | `candidate` | Local/self-hosted inference evaluation; not linked into the product workspace |
| rig | `0xPlaygrounds/rig` | vendored snapshot at enclosing repository commit `9cedc271` | MIT | `isolated-runtime` | Path dependency of the standalone `apps/agent-runtime` workspace; excluded from ReelForge's product runtime workspace |

## 3. Current production relationship

Only one direct relationship is active:

```text
apps/api/app/domains/broll/providers/comfyui_deploy.py
  → configured comfyui-deploy HTTPS endpoint
  → deployed ComfyUI workflow/machine
  → downloadable video output
  → ReelForge verifies/downloads output
  → ReelForge stores owned output in R2
```

ReelForge does not import `external/comfyui-deploy` or `external/ComfyUI` as
Python modules. The adapter speaks an HTTP contract. This isolation must remain.

The AGPL status of the checked comfyui-deploy source is operationally important:
if ReelForge modifies and operates that source as a network service, source-code
obligations require review. Calling an independently operated compatible API and
embedding/modifying its code are different adoption modes and must not be treated
as equivalent.

## 4. Project assessments

### 4.1 ComfyUI

Useful capabilities:

- modular workflow graphs;
- asynchronous job queue and partial graph execution;
- broad video-model support, including Wan;
- VRAM management, model offload, quantization, and custom nodes;
- API workflow format suitable for a provider boundary.

Recommended use:

- run as an isolated GPU runtime behind a ReelForge-owned provider adapter;
- store approved workflow JSON under `apps/api/assets/workflows` with a version,
  input schema, output-node schema, model manifest, and checksum;
- disable optional paid/API nodes unless explicitly approved;
- maintain an allowlist of custom nodes and versions.

Do not:

- expose its queue/API to first-party clients;
- mount arbitrary user workflows;
- install unreviewed custom nodes in production;
- place the full ComfyUI dependency graph in the CPU API image.

Required gate: confirm exact license/version, custom-node licenses, workflow
provenance, network exposure, output validation, and container hardening.

### 4.2 comfyui-deploy

Useful capabilities:

- versioned ComfyUI workflow deployment;
- long-running or serverless GPU machines;
- create-run/status/output API used by the current adapter;
- separation between product API and GPU execution.

Recommended use:

- keep the HTTP adapter in `apps/api`;
- pin the upstream service version and API behavior;
- keep deployment identifiers and secrets server-side;
- translate all upstream states/errors to the ReelForge B-roll domain;
- apply timeouts, retry limits, correlation ids, output download limits, and
  content/media verification.

Do not copy its control-plane database, auth, billing, or web UI into ReelForge.
ReelForge already owns those concerns.

Required gate: AGPL deployment review, source-offer obligations if modified,
tenant isolation, SSRF/output URL safety, webhook/poll authentication, and
provider availability behavior.

### 4.3 Wan2.2

Useful capabilities:

- T2V and I2V;
- 720p/24fps TI2V model option;
- cinematic and motion-oriented generation;
- ComfyUI and Diffusers ecosystem integration.

Recommended use:

- first open-model candidate for the `BrollProvider` benchmark;
- deploy through an isolated ComfyUI workflow or isolated engine adapter;
- standardize product output to portrait-compatible MP4/H.264 before R2 upload;
- record model name, revision, workflow revision, seed, input dimensions, runtime,
  GPU type, and estimated cost as job telemetry.

Required gate: exact weight license/revision, acceptable-use restrictions,
hardware envelope, warm/cold latency, commercial deployment approval, safety
controls, and output quality against the ReelForge B-roll golden set.

### 4.4 Wan2GP

Useful research:

- consumer/low-VRAM execution techniques;
- quantized model and offload strategies;
- post-processing options;
- API shape and local generation UX.

Recommendation: research source only. Its community license and extensive
third-party component set make direct code adoption more complex than using an
approved Wan implementation behind ComfyUI or the product engine.

### 4.5 VideoTuna

Useful research:

- unified T2V/I2V/V2V experimentation;
- fine-tuning, continuous training, preference alignment, and evaluation;
- cross-model benchmarks.

Recommendation: rejected as a product runtime dependency under the checked
CC-BY-NC-ND terms. It may inform benchmark design at a conceptual level. Do not
copy, modify, train, or deploy its code for the commercial product without
separate written authorization and legal approval.

### 4.6 VideoX-Fun

Useful research:

- multi-GPU inference patterns;
- Wan/CogVideo-related training and LoRA workflows;
- distributed inference configuration.

Recommendation: reference only until a specific algorithm or published package
is selected. Each referenced model and LoRA has its own license and must be
tracked independently from the repository's Apache-2.0 code license.

### 4.7 ViewComfy

Useful research:

- converting workflow inputs into user-facing forms;
- workflow routing and validation UX;
- serverless workflow connection patterns.

Recommendation: do not adopt as a first-party client. ReelForge already has web,
mobile, and desktop products, identity, billing, and sharing. Its concepts may
inform internal workflow administration, but importing its application would
duplicate product layers and introduce AGPL obligations.

### 4.8 hyvideo

Useful research:

- HunyuanVideo inference, VAE, scheduler, text encoder, and pipeline code.

Recommendation: no runtime use. The checked snapshot lacks a recorded origin and
an established top-level license in this inventory. Resolve provenance before
any deeper evaluation. Prefer an approved upstream package or model integration.

### 4.9 Faceless / brainrot pipelines (OBrainRot, FullyAutomated…, RedditVideoMakerBot, brainrot-generator)

These are **prior art for ReelForge's own mechanics** — the script → TTS → caption →
background → ffmpeg pipeline the product already runs on its Celery/Redis + ElevenLabs
stack. Their value is design reference, not code adoption:

- **OBrainRot** — caption-timing without a paid aligner: Coqui **xTTSv2** for TTS, then
  **wav2vec2 forced alignment** to sync captions, then ffmpeg stitch. Directly relevant
  to keeping ReelForge's alignment self-hosted (compare against the ElevenLabs
  `/with-timestamps` timing authority, which stays the single source of truth).
- **FullyAutomatedRedditVideoMakerBot** — ElevenLabs **API-key rotation** for scale and a
  **Playwright** TikTok/IG/YT uploader. The uploader is browser automation and is
  platform-ToS-risky; ReelForge's native publishing uses **official platform APIs**
  (`app/domains/publishing/connectors/`), not headless-browser upload. Mine the
  key-rotation and retry ideas only.
- **RedditVideoMakerBot** — the canonical, highest-star reference implementation of the
  whole faceless pipeline. Read its ffmpeg composition + caption styling steps.
- **brainrot-generator** — config layout for swappable background/voice/music with a web UI.

Recommendation: **reference only.** Three of the four are **GPL-3.0** (or license-unconfirmed);
their code MUST NOT be copied or linked into ReelForge product source. Study the FFmpeg
composition, caption-timing, and (non-browser) distribution ideas; re-implement independently.

### 4.10 Open-Higgsfield-AI (multi-model studio UI)

Useful research:

- one-key, one-balance studio UX over a very large model catalog (Video Studio across
  40+ text-to-video and 60+ image-to-video models; Lip Sync Studio across 9 models);
- how a Higgsfield-class product presents 200+ hosted model APIs behind a single picker,
  credits view, and job/history surface.

This is a **UI/UX reference for ReelForge's already-built unified media gateway**
(`apps/api/app/domains/gateway/` + `apps/web/src/features/media-gateway/` + the mobile
`media-gateway` screen), which is the same "one key → any image/video model + credits/usage"
pattern but with **real product-owned provider adapters and wallet metering**. These clones are
thin wrappers over hosted APIs, so they inform presentation, not architecture.

Recommendation: **reference only**, and confirm the license before cloning (SPDX unresolved).
Do not fork the application — ReelForge already owns identity, billing, wallet, and sharing.
`Layer AI` (node-based studio) is listed for the same UX-reference purpose but its upstream URL
is unresolved: **do not clone until provenance and license are confirmed.**

### 4.11 AnimateDiff / Stable Video Diffusion (open motion models)

- **AnimateDiff** (`guoyww/AnimateDiff`, Apache-2.0 code) — motion-module animation / I2V; a
  candidate to benchmark behind the ComfyUI B-roll adapter like Wan2.2. Motion-module and base
  checkpoint **weights carry their own licenses** — gate each independently.
- **Stable Video Diffusion** (`Stability-AI/generative-models`, MIT code) — I2V reference, but
  the SVD **weights are under Stability's non-commercial research license** → `rejected-runtime`
  for the commercial product. Code patterns may inform an isolated engine; weights may not ship.

### 4.12 Pixelle-Video

`AIDC-AI/Pixelle-Video` (Apache-2.0 per README) is a self-hostable **short-video
generation engine**: topic → AI script → images → voice narration → music → composed
video. Architecturally it is a modular pipeline with multiple backends — **ComfyUI
workflows** (local), a **RunningHub** cloud-workflow API, and **direct model APIs**
(OpenAI, DashScope, Kling, Seedance, Volcengine ARK) — behind a Streamlit UI, spanning
T2I (Flux), T2V (WAN 2.1, Kling), I2V, motion transfer, digital-human narration, and
multiple TTS engines (Edge-TTS, Index-TTS).

Two adoption modes to keep strictly separate:

- **As an application: reject.** Its topic → script → TTS → compose pipeline and its
  Streamlit UI **directly duplicate ReelForge's own product** (the MoneyPrinterTurbo-
  descended `apps/api` pipeline + the web/mobile/desktop clients + wallet/gateway). Do
  not fork the app or import its orchestration; ReelForge already owns identity, billing,
  wallet, ownership, and sharing.
- **As a B-roll provider: candidate.** Its **ComfyUI T2V/I2V workflows** (WAN 2.1, motion
  transfer) are the relevant surface — evaluate them behind the existing
  `BrollProvider` adapter exactly like Wan2.2 (§4.3), through an isolated ComfyUI runtime,
  never as an in-process dependency. Its direct-model-API bypass and RunningHub paths are
  **not** adopted: ReelForge routes hosted models through its own metered gateway adapters.

Useful research:

- workflow-vs-direct-API backend switching and a "zero-cost" local ComfyUI/Ollama mode;
- caption/narration + music assembly ordering to compare against the incumbent pipeline;
- the model catalog (Flux / WAN 2.1 / Kling) as B-roll benchmark targets.

Required gate (to move the B-roll workflows past `reference`): exact ComfyUI workflow
provenance + `workflow_sha256`, per-model **weight** licenses (Apache-2.0 covers the repo
code, not the checkpoints), acceptable-use/commercial terms, isolated GPU runtime,
SSRF-safe output retrieval, and a golden-set comparison against the current provider —
i.e. the full §5 checklist. The repo's Apache-2.0 is a **code** license only.

## 5. Adoption checklist

Every proposal to move a project beyond `reference` must add a dated decision
record containing:

### Provenance and licensing

- upstream repository URL and immutable commit/tag;
- repository software license;
- every model-weight, LoRA, VAE, tokenizer, dataset, and custom-node license;
- commercial/network-use and redistribution constraints;
- attribution/source-offer obligations;
- legal reviewer and approval date.

### Architecture

- product-owned interface implemented;
- isolated process/container boundary;
- no direct client access;
- explicit input and result schema;
- health/readiness signal;
- timeout, cancellation, retry, and idempotency semantics;
- output ownership and R2 ingestion path;
- fallback/provider-disabled behavior.

### Security

- image and dependency vulnerability scan;
- custom-node allowlist;
- no arbitrary code/workflow execution from client input;
- outbound network policy;
- SSRF-safe output retrieval;
- secrets from an approved secret store;
- untrusted media size/type/duration validation;
- prompt/content safety boundary.

### Operations and cost

- supported GPU type, VRAM, CUDA/PyTorch versions;
- cold start, p50/p95 latency, throughput and concurrency;
- cost per successful and failed generation;
- model download/cache strategy;
- rollback and version pinning;
- logs, metrics, correlation ids, and Sentry behavior;
- named operational owner.

### Product quality

- T2V/I2V support actually required by ReelForge;
- portrait output behavior;
- motion, subject, temporal consistency and artifact review;
- bitrate, codec, duration, and preview compatibility;
- reproducibility metadata;
- golden-set comparison against the incumbent provider.

## 6. Workflow manifest required for production

Each approved ComfyUI workflow receives a product-owned manifest:

```yaml
id: reelforge-broll-wan22-t2v-v1
provider: comfyui
mode: t2v
workflow_file: wan22_t2v_v1.json
workflow_sha256: "..."
model:
  name: Wan2.2-T2V
  revision: "..."
  weights_license: Apache-2.0-reviewed
inputs:
  prompt: { required: true, max_length: 1000 }
  seed: { required: false, type: integer }
outputs:
  video_node: "..."
  expected_container: mp4
limits:
  timeout_seconds: 300
  max_output_bytes: 104857600
operations:
  owner: generation-platform
  approved_at: YYYY-MM-DD
```

The manifest belongs in product source; model weights and provider secrets do not.

## 7. Immediate decisions

1. Keep comfyui-deploy behind the existing B-roll provider adapter.
2. Evaluate ComfyUI + Wan2.2 as the primary self-hosted open-model combination.
3. Keep the built-in Pixelle engine as a separately benchmarked provider option.
4. Do not integrate VideoTuna, ViewComfy, Wan2GP, VideoX-Fun, or hyvideo directly.
5. Never let `external/` become a catch-all dependency folder; every addition must
   be registered with purpose, commit, license, and intended state.
6. Treat the faceless/brainrot pipelines (OBrainRot, FullyAutomated…, RedditVideoMakerBot,
   brainrot-generator) and the studio-UI clones (Open-Higgsfield-AI, Layer AI) as
   **reference only** — GPL/unconfirmed licenses forbid copying code into product source.
   Re-implement any borrowed idea independently. Distribution stays on official platform
   APIs, never headless-browser upload.
7. Stable Video Diffusion weights are non-commercial → `rejected-runtime`. AnimateDiff is a
   reference/benchmark candidate behind the ComfyUI adapter, with per-weight license gating.
