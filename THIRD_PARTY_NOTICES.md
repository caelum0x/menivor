# Third-Party Notices

ReelForge is built on permissively-licensed upstream projects whose code has
been **ported into product source** (not vendored under `external/`). The
foundational two are MIT-licensed, which permits modification and redistribution
**provided the original copyright and permission notice are retained**. This file
is the consolidated attribution record; see
[`external/REGISTRY.md` §0](external/REGISTRY.md) for the lineage narrative.

> **Relay/agent OSS addendum:** the Rust projects adopted for the Relay gateway
> and agent runtime (TensorZero — Apache-2.0, promoted to `apps/relay`; rig,
> mistral.rs, candle) are recorded separately in
> [`docs/relay/VENDORED-OSS.md`](docs/relay/VENDORED-OSS.md). **No GPL code was
> vendored** (Helicone ai-gateway was deliberately excluded).

> Scope: this covers the *ported foundations*. The research checkouts under
> `external/` (ComfyUI, Wan2.2, etc.) are inventoried with their own licenses in
> `external/REGISTRY.md` and are not redistributed as product source.

---

## 1. MoneyPrinterTurbo — `apps/api` backend

- **Upstream:** https://github.com/harry0703/MoneyPrinterTurbo
- **License:** MIT — `Copyright (c) 2024 Harry`
- **Notice location:** the repository-root [`LICENSE`](LICENSE) **is** MoneyPrinterTurbo's
  original MIT license, retained verbatim. This satisfies the MIT notice obligation
  for the ported backend.
- **What was ported:** the FastAPI service and the `controllers/v1/{video,voice,music,subtitle}`
  surface, the script → TTS → subtitle → compose pipeline, and much of `app/services/*`
  descend from MoneyPrinterTurbo. ReelForge extended it into the wallet / media-gateway /
  reels product. (The MPT legacy `/videos` and `/audio` routes are why the media gateway
  is namespaced under `/media/*` — see [ADR 0003](docs/adr/0003-media-gateway-namespacing.md).)

## 2. OpenCut — timeline editor

- **Upstream:** https://github.com/OpenCut-app/OpenCut
- **License:** MIT — `Copyright 2026 OpenCut`
- **Notice location:** [`apps/web/editor-module/LICENSE`](apps/web/editor-module/LICENSE)
  holds OpenCut's upstream MIT license verbatim (copyright line retained), satisfying
  the MIT notice obligation for the ported editor source. ✅ Resolved.
- **What was ported:** the non-destructive timeline editor. Preserved OpenCut source
  lives in `apps/web/editor-module`; its former Elysia worker is retained as the
  stateless `apps/web/editor-bff` transport seam; the active product editor is
  `apps/web/src/features/editor` (composed by `apps/web/app/editor/page.tsx`). The same
  timeline model extends to mobile (`apps/mobile/app/editor.tsx`) and desktop
  (`rf-project::timeline`).

## 3. pyvideotrans — "Dub any video" sidecar (separate program, NOT ported)

- **Upstream:** https://github.com/jianchang512/pyvideotrans (pinned tag `v4.13`)
- **License:** GPL-3.0
- **How it is used:** built into its own container image from
  [`apps/api/sidecars/pyvideotrans/Dockerfile`](apps/api/sidecars/pyvideotrans/Dockerfile)
  and run by the Celery worker as a one-shot `docker run --rm ... cli.py --task vtv`
  subprocess (`apps/api/app/domains/dub/sidecar.py`). Menivor exchanges only files on
  a bind-mounted work dir and CLI arguments with it. **No Menivor module imports
  pyvideotrans**, and no pyvideotrans code is part of any Menivor web, desktop, iOS or
  Android binary.
- **Source availability:** the image contains the unmodified upstream source at the
  pinned tag under `/app`. If we ever distribute the image, the GPL-3.0 text and that
  source go with it. Menivor does not modify pyvideotrans; the image adds only an
  entrypoint script that writes per-run settings into its `params.json`.

## 4. Real-ESRGAN image upscale sidecar (Wave P PM2.1; separate program, NOT ported)

- **Upstream:** https://github.com/xinntao/Real-ESRGAN (package `realesrgan==0.3.0`, weights
  `RealESRGAN_x4plus.pth` from release `v0.1.0`, SHA-256 pinned in the Dockerfile)
- **License:** BSD-3-Clause. Dependencies in the image: BasicSR (Apache-2.0), PyTorch (BSD-3-Clause).
- **How it is used:** installed unmodified in its own container
  ([`deploy/esrgan-ncnn/Dockerfile`](deploy/esrgan-ncnn/Dockerfile)); Menivor calls it over
  HTTP from `apps/api/app/services/enhance/esrgan_cpu.py`. No Menivor module imports it.

## 5. Remote models called over an API (no code or weights shipped by Menivor)

- **SeedVR2 video upscale** (weights Apache-2.0) through the fal queue:
  `apps/api/app/services/enhance/seedvr_api.py`.
- **Practical-RIFE** frame interpolation (MIT), run in our own GPU worker on RunPod Serverless,
  called from `apps/api/app/services/enhance/rife.py`. The worker image is built outside this
  repository; if its code is ever vendored here, it gets a section above with its MIT notice.

## 6. Apps shelf dependencies (Wave P PM2.2)

- **rembg** (MIT, https://github.com/danielgatis/rembg) with the **BiRefNet** model (MIT), the existing
  optional `rembg[cpu]` extra, imported unmodified by `apps/api/app/domains/apps_shelf/runners.py`.
  The Remove background app is hidden on a server where it is not installed.
- **FLUX.1 Kontext [pro]** image edits are called over the fal API (commercial terms, no weights shipped).

## 7. shaka-packager (Wave P PM2.4; separate binary, NOT ported)

- **Upstream:** https://github.com/shaka-project/shaka-packager, pinned `v3.9.3`
  (`apps/api/sidecars/shaka-packager/VERSION`, SHA-256 per platform in `SHA256SUMS`).
- **License:** BSD-3-Clause (LICENSE file; the GitHub API reports NOASSERTION).
- **How it is used:** the unmodified release binary is fetched and checksum-verified at image
  build (`fetch.sh`) and verified again before every packaging job; Menivor runs it as a
  subprocess (`apps/api/app/services/ott_package/packager.py`). The binary is not committed.

## 8. OTT web player dependencies (Wave P PM2.5)

- **hls.js** 1.7.3 (Apache-2.0; LICENSE file, the GitHub API reports NOASSERTION) and
  **media-chrome** 4.19.3 (MIT), unmodified npm dependencies of `apps/web`, loaded only on
  OTT pages. Their licence texts ship inside the packages.

## 9. Wave P P3 OTT servers and apps (PM3.3, PM3.4, PM3.5)

- **MediaMTX** 1.21.1 (MIT, bluenviron/mediamtx): the unmodified release image runs as a
  separate live server (`deploy/menivor-live/`); Menivor only adds curl, jq and hook scripts
  in its own image layer.
- **Eyevinn Channel Engine** 5.1.3 (Apache-2.0): an unmodified npm dependency of the FAST
  playout service (`deploy/menivor-fast/`), used through its public asset-manager API.
- **react-native-tvos** (MIT), **@react-native-tvos/config-tv** (MIT), **expo-video** (MIT)
  and **react-native-google-cast** (MIT): unmodified dependencies of `apps/watch`; the app's
  `licence:check` script fails the build on any GPL, LGPL or AGPL package.
- **fastembed** 0.8.1 (Apache-2.0): pinned in `requirements.txt` for the API and worker
  images (discovery search and related titles, BAAI/bge-small-en-v1.5 through onnxruntime,
  MIT). A built-in hashing embedder is the fallback. Not vendored.
- **googlecast/CastReceiver** (Apache-2.0, Copyright 2022 Google LLC, commit `ddfb06c`): the
  structure of `apps/watch/cast-receiver/receiver.js` and `index.html` (the LOAD interceptor
  pattern). Notice in `apps/watch/cast-receiver/NOTICE`. No media, images or analytics agents
  were copied.
- **expo-web-browser** (MIT): an unmodified dependency of `apps/watch` that opens the
  creator's hosted checkout.
- The ad client (`apps/web/src/features/ott-player/ads.ts`) is our own VAST 4.2 parser; no
  third-party ad SDK is included.

## 10. Very ___ Time chest-text OCR (2026-10-05)

- **RapidOCR** (`rapidocr-onnxruntime` 1.4.4, Apache-2.0, https://github.com/RapidAI/RapidOCR) with
  the **PP-OCR** ONNX detection, classification and recognition models it bundles (PaddleOCR,
  Apache-2.0), run on **onnxruntime** (MIT). Pinned in `requirements.txt`; used unmodified by
  `apps/api/app/domains/film/chest_check.py` to read the garment chest text on generated stills.
- Its dependencies: **opencv-python** 5.0.0.93 (Apache-2.0), **pyclipper** 1.4.0 (MIT) and
  **shapely** 2.1.2 (BSD-3-Clause), installed unmodified. Licences read from the installed
  package metadata on 2026-10-05. Not vendored.

---

## 11. LDNOOBW word lists (data; Very ___ Time guard-rail)

- **Upstream:** https://github.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words
  at commit `5faf2ba42d7b1c0977169ec3611df25a3c08eb13` (files `en`, `tr`, `de`).
- **License:** Creative Commons Attribution 4.0 International (CC-BY-4.0). Attribution:
  "List of Dirty, Naughty, Obscene, and Otherwise Bad Words" by Shutterstock and contributors.
- **What was copied:** only a reviewed subset of slurs, into
  `apps/api/assets/moderation/hate_terms.json` (category key `upstream`), folded to
  lowercase without accents. Changes: selection and folding; curated additions are ours.

---

## Maintenance

- Any future project moved to `ported-source` in `external/REGISTRY.md` must be added
  here with its upstream, license, notice location, and what was ported.
- Keep the root `LICENSE` (MoneyPrinterTurbo MIT) intact; adding ReelForge's own
  copyright is fine, but the upstream notice must remain.
