# Publishing Menivor to Google Play

Package: `com.menivor.app` (note: iOS is `com.arhansuba.menivor`; the Android package is fixed
forever by the first upload). Expo slug `menivor`, version 1.0. Set `android.versionCode` in
`app.json` before the first build (it is not set yet; EAS production uses `autoIncrement`).

## Signing
- Upload key: `~/.config/products-keys/menivor/upload.properties` (outside the repo, mode 600; it
  names the keystore path, alias and passwords). Never print, copy or commit it. Keep an offline
  backup of the properties file and the keystore it points to.
- `plugins/withAndroidUploadSigning.js` (wired in `app.json` with `"keyDir": "menivor"`) injects
  the release signing config into `android/app/build.gradle` at prebuild. `ANDROID_UPLOAD_PROPERTIES`
  overrides the path for CI. If the file is missing, the release build silently falls back to the
  debug key, and Play rejects that bundle. Check the signer before uploading.
- Play App Signing is expected: Google holds the app signing key and this key is only the upload
  key. After the first upload, the app signing key's SHA-1/SHA-256 appear under Test and release >
  App integrity. Then:
  1. Add that fingerprint in Android developer verification (Play Console developer account).
  2. Add the SHA-1 of both the upload key and the app signing key to the Android OAuth client in
     Google Cloud, or Google sign-in fails on Play installs.
  3. Publish `https://menivor.com/.well-known/assetlinks.json` with the app signing SHA-256, or
     the `menivor.com/r/` and `/invite/` App Links (`autoVerify: true` in `app.json`) will not
     verify.

## 1. Owner steps (Console UI)
1. Play Console > Create app: name "Menivor: AI Video Reels", default language English (US), App
   (not game), Free (in-app purchases). Accept the declarations.
2. Users and permissions: invite the publishing service account with "Release to testing tracks",
   "Manage store presence" and "View app information" for this app.
3. Store settings: category Video Players & Editors, contact email hello@menivor.com, website
   https://menivor.com/.
4. App content: Privacy policy https://menivor.com/privacy; Data safety from `DATA-SAFETY.md`;
   content rating from `CONTENT-RATING.md`; Ads = No; Target audience = 18+; App access per
   `DATA-SAFETY.md`; data deletion URL (see the OWNER item there).
5. Monetization: create the RevenueCat Play products (plans and credit packs) and a RevenueCat
   Android app, then set `EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY` in the EAS production
   environment. It is missing from `eas.json` today, so Android builds have no purchases.
6. Store listing assets: `listing.json` > images.todo lists what still has to be produced.

## 2. Build the AAB
Use the same prebuild + Gradle `bundleRelease` route as the reference kit
(`vertex/store/play/PUBLISHING.md`), from `apps/mobile`, with the upload properties in place.
Copy the result to `store/play/build/menivor-<version>-vc<code>.aab` (do not commit AABs).
Raise `android.versionCode` for every upload.

## 3. Publish through the API
`store/play/publish.mjs` (identical to the reference) runs edits.insert > bundle upload > track
`alpha` release (status `draft`) > listing text > details > images > commit, reading `listing.json`
from its own folder:
```
GOOGLE_PLAY_SA_KEYCHAIN_SERVICE=<service> node store/play/publish.mjs --aab <aab> --dry-run
GOOGLE_PLAY_SA_KEYCHAIN_SERVICE=<service> node store/play/publish.mjs --aab <aab>
```
Note: the script's hard-coded release note text says "First release of Comet Lanes." Edit that
one string (or the release notes in the Console) before the first real run. It also needs every
image in `listing.json` to exist.

## 4. Closed test (personal developer account rule)
The account is a personal account created after 13 Nov 2023, so production access needs a closed
test first:
1. Testing > Closed testing: use track `alpha`. Add testers through a Google Group (for example
   menivor-testers@googlegroups.com).
2. At least **12 testers opted in for 14 continuous days**. Aim for 15 to 20 so a few dropouts do
   not reset the clock (it restarts if the count drops below 12).
3. Ship at least one update to the closed track during the 14 days (bump versionCode).
4. Dashboard > Apply for production. Google reviews the answers about the test (usually up to
   7 days). Only then can a release go to `production`.

Tester invitation message:
> I am testing Menivor, an app that turns a screen recording, a link or a topic into a captioned
> vertical video. Join the group <group link>, then open <opt-in link> and install it from Google
> Play. Please keep it installed for 14 days, make one or two reels, and tell me anything that
> breaks or feels confusing.

## 5. Known blockers (from MOBILE-FIXALL-2026-10-06.md and this audit)
- Shared Supabase project `psqkkdjzgptfcqpxuxki` is dead (NXDOMAIN). `app.json` extra.auth is
  empty, so Apple/Google sign-in depends on whatever EAS env provides; if that still points at the
  dead project, social sign-in fails. Move auth to the Menivor Scribase project first. Play also
  rejects apps whose login is broken.
- Guest flow: "Start creating" makes an anonymous device account. This conflicts with the owner's
  signup-first rule (owner decision); it does make review access easy.
- Dev/lab and crypto-looking screens (hook lab, retention lab, diffusion lab, effects lab,
  developer, wallet "Send tokens" and `ait1` addresses) are reachable. Hide them in store builds.
- No in-app report action for AI-generated output (Play generative AI policy). See
  CONTENT-RATING.md.
- No RevenueCat Android key (step 1.5). No data-deletion web page (DATA-SAFETY.md).
- Listing images do not exist yet. `android.versionCode` not set.
- `tsc` could not run in this worktree (dependencies not installed); verify the Android build
  before the first upload.
