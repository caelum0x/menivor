# pyvideotrans sidecar (Dub any video)

pyvideotrans (GPL-3.0, pinned `v4.13`) runs as a **separate one-shot container**.
The Celery worker (`app/domains/dub/sidecar.py`) calls it with
`docker run --rm ... --task vtv` against a bind-mounted work dir and reads back the
dubbed mp4 and `.srt` files. No Menivor Python imports it (`grep -r videotrans apps/api/app`
finds CLI strings only).

## Build (not done automatically)

The image installs only the packages the dub path imports (`requirements-slim.txt`,
held to upstream's pins by `make_constraints.py`), not upstream's full ~6-8 GB set.

    docker build -t menivor/pyvideotrans:v4.13 apps/api/sidecars/pyvideotrans
    docker run --rm menivor/pyvideotrans:v4.13 --list providers

## Worker settings (env, or `[app]` keys in config.toml)

| env | `[app]` key | default | meaning |
|---|---|---|---|
| `PYVIDEOTRANS_IMAGE` | `dub_sidecar_image` | (unset = feature locked, 402 `format_locked`) | image tag to run |
| `DUB_SIDECAR_NETWORK` | `dub_sidecar_network` | none | docker network (needed to reach Relay) |
| `DUB_SIDECAR_CPUS` / `DUB_SIDECAR_MEMORY` | `dub_sidecar_cpus` / `dub_sidecar_memory` | `2` / `4g` | container limits |
| `DUB_SIDECAR_TIMEOUT_S` | `dub_sidecar_timeout_s` | `3600` | killed (`docker rm -f`) after this |
| `DUB_WORK_ROOT` | `dub_work_root` | `/tmp/menivor-dub` | per-job work dirs |
| `DUB_HOST_WORK_ROOT` | `dub_host_work_root` | same path | host path of `DUB_WORK_ROOT` when the worker itself is containerized |
| `DUB_LOCK_PATH` | `dub_lock_path` | `/tmp/menivor-dub.lock` | one dub per host (flock) |
| `DUB_TRANSLATE_MODEL` | | `claude-haiku-4-5-20251001` | model for translation via Relay (`RELAY_URL` or `RAILYARD_RELAY_URL`) |
| `DUB_SIDECAR_URL` / `DUB_SIDECAR_TOKEN` | `dub_sidecar_url` | (unset) | HTTP mode: the runner service (see below); the worker then needs no docker |

Docker mode needs the docker CLI plus the daemon socket in the worker. HTTP mode
does not: run the image as a compose service with
`entrypoint: ["python", "/usr/local/bin/menivor-pvt-runner"]`, `DUB_RUNNER_TOKEN`
(= the worker's `DUB_SIDECAR_TOKEN`) and the work dir mounted at the same path in
both containers (`DUB_WORK_ROOT` = `DUB_RUNNER_WORK_ROOT`). The runner only accepts
`--task vtv` with input/output paths inside the work root, one job at a time.
Prod (box 1) uses HTTP mode: infra-box `stacks/menivor` service `dub`.

Translation: with `RELAY_URL` set, subtitles are translated through our Relay
(OpenAI-compatible, pyvideotrans "Local LLM" engine). Without it, pyvideotrans' free
Google endpoint is used. Speech recognition is local faster-whisper (models cached in the
`menivor-pyvideotrans-models` volume). Voices: free edge-tts by default, ElevenLabs when
`ELEVENLABS_API_KEY` is set.

Credits (`[app]`): `reelforge_dub_free_cost` (2), `reelforge_dub_premium_cost` (6),
`reelforge_dub_max_seconds` (600), `reelforge_dub_max_bytes` (500 MB).
