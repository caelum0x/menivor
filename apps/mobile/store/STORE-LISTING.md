# Menivor: AI Video Maker (store kit, version 1.0)

Copy: `asc/metadata.json` (EN only; the UI has no Turkish). Review notes: `asc/review-notes.txt`.
Privacy: `PRIVACY-ANSWERS.md` (ASC App Privacy is set by the owner in the web UI). Play:
`play/listing.v2.json` (current copy, kept beside the earlier `play/listing.json`),
`play/DATA-SAFETY-ADDENDUM.md`, `play/icon-512.png`, `play/feature-graphic-1024x500.png`.

| Field | Value |
|---|---|
| App record | ASC 6809286411, bundle `com.arhansuba.menivor`; Play package `com.menivor.app` (not taken on Play, kept) |
| Name | Menivor: AI Video Maker (brand kept) |
| Subtitle | Prompt or link to a reel |
| Category | Photo & Video (secondary: Productivity) |
| Devices | iPhone only (`supportsTablet: false`; the layouts are phone layouts) |
| Age rating | 12+ suggested (user-generated prompts rendered by AI; no web browsing) |
| IAP | Menivor Pro (auto-renewing, RevenueCat offering "current") + consumable credit packs (ids from GET /credit-packs); prices are the store's priceString only |
| Support / Marketing / Privacy | https://menivor.com/contact (200) / https://menivor.com/ (200) / https://menivor.com/privacy (200) |

## Name check (iTunes Search API, US, 2026-10-06)
"menivor": 4 results, none named Menivor (0 exact matches). The owner's brand stays.

## What the store build contains
Create from a prompt, a link or footage (three hook variants), results, Reels library and render
progress, reel detail (play, export, share, cover, dub, b-roll), timeline editor, Caption Studio,
voices, presenters, dubbing, scripts, templates, brand watermark, uploads, drafts, credits and Pro,
account, privacy (export, delete), support, legal. Everything else in `app/` is dev-only
(`src/shared/release/surface.ts`, guarded by `npm run test:release`).

## Screenshots (phase 2, not made yet)
Demo data: run Metro with `EXPO_PUBLIC_MENIVOR_DEMO=1` (dev sessions only; a store build ignores it):
`EXPO_PUBLIC_MENIVOR_DEMO=1 npx expo start --go --ios --port 8102`, tap Continue with Apple
(signs into the seeded workspace without Apple in demo mode). Seeded: six projects across travel,
cooking, fitness, product demo, real estate and baking (one still rendering).
Suggested frames: sign-in reel wall; Create (prompt); three hook variants; Reels library;
reel detail with captions; Caption Studio; Pro sheet (only with real store prices from a sandbox build).
Sizes: 1320x2868 -> `screenshots/ios-6.9/`, 1284x2778 -> `screenshots/ios-6.5/`,
1080x2160 -> `screenshots/android-phone/`. No iPad set (iPhone only).

## Local builds (do not run on low disk; need > 25 GB free)
Environment for both (production values, from `eas.json` production env plus the auth project):
```
export EXPO_PUBLIC_API_BASE=https://api.menivor.com/api/v1
export EXPO_PUBLIC_WAITLIST_MODE=0
export EXPO_PUBLIC_REVENUECAT_IOS_API_KEY=<appl_ key from eas.json>
export EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY=<goog_ key, owner>
export EXPO_PUBLIC_SUPABASE_URL=<Menivor Scribase auth URL>     # or set app.json extra.auth
export EXPO_PUBLIC_SUPABASE_ANON_KEY=<its anon key>
```
iOS (archive + upload):
```
cd ~/products/.mobile-fixall/videogen && npm ci -w apps/mobile
cd apps/mobile
# bump expo.ios.buildNumber in app.json above the highest build in ASC (currently "2")
npx expo prebuild --clean --platform ios
cd ios && pod install
xcodebuild -workspace Menivor.xcworkspace -scheme Menivor -configuration Release \
  -destination 'generic/platform=iOS' -archivePath build/Menivor.xcarchive archive
xcodebuild -exportArchive -archivePath build/Menivor.xcarchive \
  -exportOptionsPlist ExportOptions.plist -exportPath build/export   # method app-store-connect, team 947G2G2JXJ
```
Android (AAB, signed with the existing upload key; nothing new created):
```
cd ~/products/.mobile-fixall/videogen/apps/mobile
npx expo prebuild --clean --platform android   # plugins/withAndroidUploadSigning reads ~/.config/products-keys/menivor/upload.properties
cd android && JAVA_HOME=/opt/homebrew/opt/openjdk@17 ./gradlew bundleRelease
# -> android/app/build/outputs/bundle/release/app-release.aab (upload key SHA-256 4A:08:88:0C:...:8E:8F)
```
