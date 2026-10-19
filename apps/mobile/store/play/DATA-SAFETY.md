# Play Console: Data safety answers (Menivor 1.0)

Basis (read from the code on branch mobile-fixall-2026-10-06, apps/mobile):
- `package.json`: `@supabase/supabase-js` (Scribase/Supabase Auth for Apple and Google sign-in),
  `@react-native-google-signin/google-signin`, `expo-apple-authentication`, `react-native-purchases`
  and `-ui` (RevenueCat), `expo-notifications` (push), `expo-image-picker`, `expo-document-picker`,
  `expo-av` (microphone), `expo-secure-store`. No ads SDK, no third-party analytics SDK, no crash
  reporting SDK. `@reelforge/growth-analytics` is a local scoring library (`app/hook-lab.tsx`,
  `app/retention-lab.tsx`) and sends nothing.
- `app.json` android.permissions: READ_EXTERNAL_STORAGE, READ_MEDIA_VIDEO, READ_MEDIA_AUDIO,
  RECORD_AUDIO, MODIFY_AUDIO_SETTINGS. Camera via the expo-image-picker plugin. No location,
  contacts, calendar or health permission.
- Network: everything goes to `https://api.menivor.com/api/v1` (`eas.json` EXPO_PUBLIC_API_BASE,
  `lib/api.ts`, `x-api-key` header). Media is uploaded through presigned URLs (`lib/api.ts`
  presignAndUpload, `lib/uploads.ts`). Push tokens are registered with the API
  (`src/shared/notifications/usePushRegistration.ts`).
- Account: "Start creating" mints a device account (`app/index.tsx`, `createDeviceSession`); Apple
  and Google sign-in are optional (`src/shared/auth/social-signin.ts`). Deletion: Settings > Danger
  zone > Delete account opens Privacy and data (`app/account/settings.tsx` -> `app/privacy.tsx`,
  PrivacyManager), which also exports data. `src/shared/auth/delete-identity.ts` removes the
  sign-in identity.

## Data collected

| Play data type | Collected | Shared | Optional? | Purposes | Source |
|---|---|---|---|---|---|
| Personal info > Email address | Yes | No | Optional (Apple/Google sign-in, beta request) | App functionality, Account management, Developer communications | `src/shared/auth/social-signin.ts`, `lib/beta.ts`, `app/beta-request.tsx` |
| Personal info > Name | Yes | No | Optional (from Apple/Google, workspace display name) | App functionality, Account management | `src/shared/auth/social-signin.ts`, `app/account/workspaces/members.tsx` |
| Personal info > User IDs | Yes | No | Required (device account id, install id) | App functionality, Account management, Fraud prevention | `app/index.tsx` getOrCreateInstallId, `lib/api.ts` |
| Financial info > Purchase history | Yes | No | Required for paid features | App functionality, Account management | `app/wallet/history.tsx`, `app/wallet/billing-history.tsx`, `src/shared/billing/revenuecat-adapter.ts` |
| Photos and videos > Photos | Yes | No | Optional (selfie for avatar, images in media gateway) | App functionality | `app.json` expo-image-picker cameraPermission, `app/account/avatars/*`, `app/media-gateway.tsx` |
| Photos and videos > Videos | Yes | No | Optional (screen recordings and imported clips for reels) | App functionality | `app/(tabs)/create.tsx`, `app/uploads.tsx`, `lib/uploads.ts` |
| Audio > Voice or sound recordings | Yes | No | Optional (voice sample for a brand voice) | App functionality | `app.json` expo-av microphonePermission, `app/voices.tsx`, `app/account/voices/*` |
| Audio > Music files / Other audio files | Yes | No | Optional (audio picked as a track or voice source) | App functionality | READ_MEDIA_AUDIO, `expo-document-picker` |
| Files and docs | Yes | No | Optional (files picked for upload) | App functionality | `expo-document-picker`, `lib/uploads.ts` |
| Messages > Other in-app messages | Yes | No | Optional (social inbox threads and replies from connected accounts, support messages) | App functionality | `lib/social-inbox.ts`, `app/inbox/[id].tsx`, `app/support.tsx` |
| App activity > Other user-generated content | Yes | No | Required (topics, scripts, prompts, brand settings, templates, ratings, drafts once uploaded) | App functionality | `app/brand.tsx`, `app/templates.tsx`, `app/marketplace.tsx`, `lib/scripts.ts` |
| App activity > Other actions | Yes | No | Required (render jobs, usage and credit spend) | App functionality, Account management | `app/usage.tsx`, `app/spend.tsx`, `lib/tasks.ts` |
| Device or other IDs | Yes | No | Optional (Expo push token, only after notification permission) | App functionality | `src/shared/notifications/usePushRegistration.ts` |

Not collected: location, contacts, calendar, health and fitness, web browsing history, installed
apps, crash logs and diagnostics (no SDK), advertising ID (no ads SDK).

Shared: **No data is shared** in Play's sense. AI model providers, storage (R2), RevenueCat and the
Expo push service process data on Menivor's behalf as service providers. Posting a reel to TikTok,
YouTube or Instagram happens only when the user connects an account and asks for it, which Play
treats as a user-initiated transfer, not sharing.

## Security practices

| Question | Answer |
|---|---|
| Is all of the user data collected by your app encrypted in transit? | **Yes**. All requests use https (api.menivor.com, presigned https upload URLs, Supabase/Scribase https) |
| Do you provide a way for users to request that their data is deleted? | **Yes**. In app: Settings > Danger zone > Delete account (`app/account/settings.tsx`). Web URL: see OWNER item below |
| Committed to Play Families Policy | No (not a Families app) |
| Independent security review | No |

Delete-account web URL (Play asks for one for every app with accounts):
OWNER: https://menivor.com/account/delete and /delete-account return 404. The privacy policy
(https://menivor.com/privacy, 200) describes deletion. Either publish a page that lets a user
request deletion without the app (form or email instruction to hello@menivor.com) and enter that
URL, or enter https://menivor.com/privacy only if it states the request steps clearly.

Privacy policy URL: https://menivor.com/privacy (HTTP 200 on 2026-10-06; real policy page,
effective 2026-09-23).

## Other App content declarations

- Ads: **No, my app does not contain ads** (no ads SDK in `package.json`).
- App access: **All functionality is available without special access** while the API reports
  public signup (`GET /api/v1/launch/status` returned `signup: true` on 2026-10-06): "Start
  creating" creates a device account with no credentials. If signup is closed again
  (private beta), the reviewer needs an access key. OWNER: put a pilot access key and the steps
  ("Use an access key" on the first screen) in App access instructions so review never hits the
  waitlist.
- Target audience: **18 and over** (AI generation, payments, public creator profiles).
- Content: Generative AI app. See CONTENT-RATING.md for the missing in-app report action.
- News app: No. Health app: No. Government app: No.
- Financial features: **None** to declare (credits are a prepaid balance for the app's own
  service). Risk: the Wallet has "Send tokens" to another user's handle and shows an `ait1...`
  receive address (`app/wallet/transfer.tsx`, `app/wallet/index.tsx`). A reviewer can read that as
  a crypto wallet or money transfer. Recommended: hide the transfer and receive-address screens in
  Play builds, the same way store builds already hide the web checkout.
- Advertising ID: **No** (no ads SDK; confirm the merged manifest has no AD_ID permission after
  the first build).
