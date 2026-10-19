# ReelForge / Menivor API image. Build context = repository ROOT.
#
# Targets (both multi-arch: python:3.11-slim ships amd64 + arm64, and Playwright
# publishes linux-arm64 Chromium builds, so this builds natively on either):
#   api     (default, last stage) — FastAPI + Celery beat/migrate. No browser.
#   worker  — api + Playwright Chromium and its system libraries, for URL
#             captures (app/domains/capture) and the TikTok trends puller.
#
#   docker build -f apps/api/Dockerfile .                   # api
#   docker build -f apps/api/Dockerfile --target worker .   # worker
#
# Compose: set `build.target: worker` on the worker service only, so the api /
# migrate / beat images stay free of the ~450 MB browser layer.
FROM python:3.11-slim AS base

WORKDIR /workspace
ENV PYTHONPATH=/workspace/apps/api:/workspace
ENV REELFORGE_BACKEND_ROOT=/workspace/apps/api
# Discovery embeddings (fastembed) keep their model on the worker model-cache volume.
ENV FASTEMBED_CACHE_PATH=/root/.cache/fastembed

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-adclone.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-adclone.txt
COPY . .
RUN pip install --no-cache-dir --no-deps ./packages/provider-adapter-kit

EXPOSE 8080
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8080"]

# ---- worker: base + Playwright Chromium -------------------------------------
FROM base AS worker

# Browsers live OUTSIDE /root/.cache: the worker mounts a model-cache volume on
# /root/.cache, which would otherwise shadow Playwright's default browser dir.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# `playwright` (pinned in requirements.txt) resolves the right build for the
# image's architecture (linux-x64 or linux-arm64). --with-deps apt-installs the
# shared libraries Chromium needs. Full `chromium` (not --only-shell): the
# TikTok puller launches headful Chromium with --headless=new.
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /tmp/* \
    && chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"

# ---- api (default target) ----------------------------------------------------
# Kept LAST so a plain `docker build` (and any compose service without a target)
# still produces the browser-free image exactly as before.
FROM base AS api
