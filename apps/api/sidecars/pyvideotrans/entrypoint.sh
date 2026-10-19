#!/bin/sh
# Copy per-run secrets from the environment into pyvideotrans' params.json,
# then run its CLI with the arguments we were given.
#
#   PVT_ELEVENLABS_KEY  -> elevenlabstts_key
#   PVT_LLM_API         -> localllm_api   (OpenAI-compatible base URL, e.g. Relay)
#   PVT_LLM_KEY         -> localllm_key
#   PVT_LLM_MODEL       -> localllm_model
#
# Values arrive as inherited env vars (never on the docker argv).
set -eu

python - <<'PY'
import json, os
path = "/app/videotrans/params.json"
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except (OSError, ValueError):
    data = {}
mapping = {
    "PVT_ELEVENLABS_KEY": "elevenlabstts_key",
    "PVT_LLM_API": "localllm_api",
    "PVT_LLM_KEY": "localllm_key",
    "PVT_LLM_MODEL": "localllm_model",
}
# Every managed key is written on every run (empty when not given), so in the
# long-lived runner one job's secrets never carry over into the next job.
for env_name, key in mapping.items():
    data[key] = os.environ.get(env_name, "").strip()
# pyvideotrans merges a params.json with its defaults but indexes this key
# unconditionally (configure/_app_params.py), so a file without it crashes.
data.setdefault("f5tts_role", "")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False)
PY

cd /app
exec python cli.py "$@"
