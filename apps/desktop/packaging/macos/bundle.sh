#!/usr/bin/env bash
# Assemble a Menivor.app with a verified, self-contained media toolchain.
# Usage: packaging/macos/bundle.sh --ffmpeg /path/ffmpeg --ffprobe /path/ffprobe [--sign "Developer ID Application: …"]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../../.." && pwd)"
bin="$root/target/release/reelforge-desktop"
app="$root/target/Menivor.app"
ffmpeg=""
ffprobe=""
sign_id=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --ffmpeg) [ "$#" -ge 2 ] || { echo "--ffmpeg needs a path" >&2; exit 2; }; ffmpeg="$2"; shift 2 ;;
    --ffprobe) [ "$#" -ge 2 ] || { echo "--ffprobe needs a path" >&2; exit 2; }; ffprobe="$2"; shift 2 ;;
    --sign) [ "$#" -ge 2 ] || { echo "--sign needs an identity" >&2; exit 2; }; sign_id="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[ -n "$ffmpeg" ] && [ -n "$ffprobe" ] || { echo "--ffmpeg and --ffprobe are required" >&2; exit 2; }
[ -f "$bin" ] || { echo "build first: cargo build --release -p reelforge-desktop"; exit 1; }
"$here/../verify-media-toolchain.sh" "$ffmpeg" "$ffprobe"

# A release binary linked directly to a developer machine's Homebrew/MacPorts
# prefix is not portable. System libraries and loader-relative dependencies are
# safe; everything else must be bundled and rewritten before this script runs.
for media_bin in "$ffmpeg" "$ffprobe"; do
  while IFS= read -r dependency; do
    case "$dependency" in
      ""|/System/Library/*|/usr/lib/*) ;;
      *) echo "non-portable dependency in $media_bin: $dependency" >&2; exit 1 ;;
    esac
  done < <(otool -L "$media_bin" | tail -n +2 | awk '{print $1}')
done

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources/bin"
cp "$here/Info.plist" "$app/Contents/Info.plist"
cp "$bin" "$app/Contents/MacOS/reelforge-desktop"
cp "$ffmpeg" "$app/Contents/Resources/bin/ffmpeg"
cp "$ffprobe" "$app/Contents/Resources/bin/ffprobe"
chmod 755 "$app/Contents/Resources/bin/ffmpeg" "$app/Contents/Resources/bin/ffprobe"
[ -f "$here/Menivor.icns" ] && cp "$here/Menivor.icns" "$app/Contents/Resources/"

if [ -n "$sign_id" ]; then
  codesign --force --options runtime --sign "$sign_id" "$app/Contents/Resources/bin/ffmpeg"
  codesign --force --options runtime --sign "$sign_id" "$app/Contents/Resources/bin/ffprobe"
  codesign --force --options runtime \
    --entitlements "$here/entitlements.plist" \
    --sign "$sign_id" "$app"
  codesign --verify --deep --strict "$app"
  echo "signed + verified"
fi
echo "built $app"
