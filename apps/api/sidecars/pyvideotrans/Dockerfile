# pyvideotrans CLI sidecar for Menivor "dub any video" (CPU, one-shot).
#
# LICENSE BOUNDARY: pyvideotrans is GPL-3.0 (jianchang512/pyvideotrans). This
# image is a separate program. Menivor's worker runs it with
#   docker run --rm <image> --task vtv ...
# and exchanges only files on a bind-mounted work dir. No Menivor code imports
# it and no GPL code ships in any Menivor web/mobile binary. The upstream
# source at the pinned tag is included in the image (/app), which satisfies
# the GPL source-availability requirement for anyone we give the image to.
#
# Build (x86_64 box; slim dependency set, see requirements-slim.txt):
#   docker build -t menivor/pyvideotrans:v4.13 apps/api/sidecars/pyvideotrans
# Smoke test:
#   docker run --rm menivor/pyvideotrans:v4.13 --list languages
FROM python:3.10-slim

ARG PYVIDEOTRANS_REF=v4.13
ARG TORCH_VERSION=2.7.1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FONTCONFIG_PATH=/etc/fonts \
    HF_HOME=/app/models/hf

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /bin/uv

# ffmpeg from Debian (the upstream Dockerfile pulls an unpinned static build).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git ca-certificates fontconfig fonts-noto-core fonts-dejavu \
        libsndfile1 rubberband-cli libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pinned upstream release (tag), shallow clone, no git history in the image.
RUN git clone --depth 1 --branch "${PYVIDEOTRANS_REF}" \
        https://github.com/jianchang512/pyvideotrans.git /app \
    && rm -rf /app/.git

# CPU torch first so the dependency set never pulls CUDA wheels. Then only the
# packages the Menivor dub path imports (requirements-slim.txt), held to the
# versions upstream pins in pyproject.toml. Installing the whole upstream
# pyproject instead adds ~5 GB of engines Menivor never selects.
COPY requirements-slim.txt make_constraints.py /tmp/build/
RUN uv pip install --system "torch==${TORCH_VERSION}" "torchaudio==${TORCH_VERSION}" \
        --index-url https://download.pytorch.org/whl/cpu \
    && python /tmp/build/make_constraints.py /app/pyproject.toml > /tmp/build/constraints.txt \
    && uv pip install --system -c /tmp/build/constraints.txt -r /tmp/build/requirements-slim.txt \
    && python -c "import torch, faster_whisper, edge_tts, PySide6.QtCore" \
    && rm -rf /root/.cache /tmp/*

COPY entrypoint.sh /usr/local/bin/menivor-pvt-entrypoint
# Optional long-lived mode (compose service): runner.py serves POST /run and
# executes the same entrypoint, so the Celery worker needs no docker socket.
COPY runner.py /usr/local/bin/menivor-pvt-runner
# The worker runs the container as its own uid:gid so it can clean up the
# bind-mounted work dir; pyvideotrans writes to /app/{models,tmp,logs}.
RUN chmod 0755 /usr/local/bin/menivor-pvt-entrypoint /usr/local/bin/menivor-pvt-runner \
    && mkdir -p /app/models /app/tmp /app/logs /app/output \
    && chmod -R a+rwX /app

ENV HOME=/tmp
ENTRYPOINT ["/usr/local/bin/menivor-pvt-entrypoint"]
CMD ["--help"]
