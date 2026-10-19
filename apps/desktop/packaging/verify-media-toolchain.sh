#!/usr/bin/env bash
# Fail closed unless the supplied release FFmpeg/ffprobe pair supports every
# operation used by Menivor's local timeline renderer.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 /absolute/path/to/ffmpeg /absolute/path/to/ffprobe" >&2
  exit 2
fi

ffmpeg="$1"
ffprobe="$2"

case "$ffmpeg" in /*) ;; *) echo "ffmpeg path must be absolute" >&2; exit 2 ;; esac
case "$ffprobe" in /*) ;; *) echo "ffprobe path must be absolute" >&2; exit 2 ;; esac
[ -f "$ffmpeg" ] && [ -x "$ffmpeg" ] || { echo "ffmpeg is not an executable regular file: $ffmpeg" >&2; exit 1; }
[ -f "$ffprobe" ] && [ -x "$ffprobe" ] || { echo "ffprobe is not an executable regular file: $ffprobe" >&2; exit 1; }

filters="$($ffmpeg -hide_banner -filters 2>&1)"
encoders="$($ffmpeg -hide_banner -encoders 2>&1)"

has_capability() {
  table="$1"
  capability="$2"
  printf '%s\n' "$table" | awk -v capability="$capability" '$2 == capability { found = 1 } END { exit !found }'
}

for filter in ass trim atrim setpts asetpts concat overlay scale crop fps; do
  if ! has_capability "$filters" "$filter"; then
    echo "ffmpeg is missing required filter: $filter" >&2
    exit 1
  fi
done

for encoder in libx264 aac; do
  if ! has_capability "$encoders" "$encoder"; then
    echo "ffmpeg is missing required encoder: $encoder" >&2
    exit 1
  fi
done

"$ffprobe" -version >/dev/null
echo "verified Menivor media toolchain: $ffmpeg + $ffprobe"
