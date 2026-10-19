#!/usr/bin/env bash
# Menivor — local App Store build + TestFlight upload.
#
# Exports the production env from eas.json (EXPO_PUBLIC_* vars are inlined into
# the JS bundle by Metro during the Xcode "Bundle React Native code and images"
# phase — exactly what EAS cloud injected), then runs the fastlane beta lane.
#
# This app is Expo SDK 54 (no expo-modules-jsi package) and lives in apps/mobile
# of an npm workspace (dependencies are hoisted to the repo root), so there is no
# Swift 6 JSI patch to verify and node_modules lives at ../../.
#
# Usage:  ./scripts/build-production.sh [beta|upload_only|check_build] [fastlane args...]
set -euo pipefail
cd "$(dirname "$0")/.."

LANE="${1:-beta}"
shift || true

# Export every key/value from build.production.env in eas.json.
eval "$(node -e '
  const env = require("./eas.json").build.production.env ?? {};
  for (const [k, v] of Object.entries(env)) {
    console.log(`export ${k}=${JSON.stringify(String(v))}`);
  }
')"

# Sanity checks before an expensive archive.
[ -d ios ] || { echo "ios/ missing — run: npx expo prebuild -p ios --no-install && (cd ios && pod install)"; exit 1; }
# npm workspace: deps are hoisted to the repo root, not apps/mobile.
[ -d node_modules ] || [ -d ../../node_modules ] || { echo "node_modules missing — run: npm install (from repo root)"; exit 1; }

exec fastlane ios "$LANE" "$@"
