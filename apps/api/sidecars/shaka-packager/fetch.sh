#!/usr/bin/env sh
# Fetch the pinned shaka-packager (BSD-3-Clause) and refuse it unless the SHA-256 matches.
# Usage: fetch.sh <platform: linux-arm64|linux-x64|osx-arm64> <dest path>
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
VERSION=$(cat "$HERE/VERSION")
PLATFORM=$1
DEST=$2
URL="https://github.com/shaka-project/shaka-packager/releases/download/${VERSION}/packager-${PLATFORM}"
WANT=$(awk -v n="packager-${PLATFORM}" '$2==n {print $1}' "$HERE/SHA256SUMS")
[ -n "$WANT" ] || { echo "no pinned checksum for ${PLATFORM}" >&2; exit 1; }
curl -fsSL "$URL" -o "$DEST.tmp"
GOT=$( (sha256sum "$DEST.tmp" 2>/dev/null || shasum -a 256 "$DEST.tmp") | awk '{print $1}')
[ "$GOT" = "$WANT" ] || { echo "checksum mismatch for ${PLATFORM}" >&2; rm -f "$DEST.tmp"; exit 1; }
mv "$DEST.tmp" "$DEST" && chmod 0755 "$DEST"
echo "packager ${VERSION} ${PLATFORM} verified"
