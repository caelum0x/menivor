# Menivor Mobile

An [Expo](https://expo.dev) (React Native + TypeScript) app that turns a screen
recording into a vertical, captioned UGC reel. It is a full-surface product — not
a thin client — built on `expo-router` with a mature `src/features` +
`src/shared` architecture, talking to the same `/api/v1` endpoints as `apps/web`
(shared contract in
[`docs/reelforge/INTEGRATION_CONTRACT.md`](../../docs/reelforge/INTEGRATION_CONTRACT.md)).

Its visual language matches the web's editorial identity: ink/paper monochrome
with a single #FFD93D accent (the product's own caption-highlight yellow), no
gradients/glow/glass. The shared design tokens live in `src/shared/theme`.

## Waitlist mode and honest degrades

Menivor's generation pipeline requires production provider keys. Until those are
live, the app runs in **waitlist mode** (on by default; set
`EXPO_PUBLIC_WAITLIST_MODE=0` to opt into the full pilot UI once keys land). This
mirrors the web app's `NEXT_PUBLIC_WAITLIST_MODE`. There are no dead ends:

- **Sign-in fails open.** `POST /auth/device` mints a device account, but if that
  endpoint is unreachable or gated, the user is routed to the waitlist home
  instead of being trapped. Pilot users can still paste an access key.
- **The Create tab never terminates.** When `GET /pilot/capabilities` reports
  generation off, it shows a real waitlist-era home (`src/shared/product/WaitlistHome`):
  join the live waitlist (posts to the KV-backed `menivor.com/api/waitlist`),
  preview the product's caption looks, and **record/import a clip for later** as a
  device-local draft.
- **The Jobs tab isn't empty pre-backend.** It lists local drafts (with delete)
  above the reels list.

No data is fabricated: caption previews only show styles the live catalog
returns, and a signup is "on the list" only when the server confirms it.

The app also lets you:

1. **Sign in** with your Menivor access key (stored securely with
   `expo-secure-store`, sent as the `x-api-key` header) or a device account.
2. **Create** a reel: pick a screen recording (files or photo library), upload
   it via a presigned R2 URL, choose an avatar / voice / layout, and submit a job.
3. Browse your **jobs** list and local **drafts**.
4. Generate and preview AI **B-roll**, persist recent history locally, and attach
   a durable clip key to a reel draft.
5. Open a **job** to poll its status and play the finished vertical video.
6. Use the **Media Gateway** to generate image, video, or audio from one wallet;
   a completed image can be sent straight into an image-to-video model with
   **Animate image** and is polled in the foreground until the clip is ready.
7. Send AI tokens from an authorized personal or workspace source through a
   two-step review/confirm flow. The app loads that source's authoritative Mint
   balance, persists one retry key in SecureStore, and recovers ambiguous sends
   without creating a second transfer. Every source exposes a stable `ait1…`
   receive address; pasted addresses can target personal or workspace accounts
   without exposing Mint's internal account ids.

## Getting started

```bash
cd apps/mobile
npm install          # (run this yourself — not run by the generator)

cp .env.example .env
# edit .env and point EXPO_PUBLIC_API_BASE at your backend, e.g.
#   EXPO_PUBLIC_API_BASE=http://192.168.1.50:8080/api/v1

npx expo start
```

Then press `i` for the iOS simulator, `a` for Android, or scan the QR code with
the Expo Go app on a device. RevenueCat runs in Preview API Mode inside Expo Go.
Real purchases require an Expo development or store build with native modules.

> **Physical devices:** `localhost` refers to the phone, not your dev machine.
> Set `EXPO_PUBLIC_API_BASE` to your computer's LAN IP.

## Configuration

The Expo icon, Android adaptive foreground, splash mark, and favicon are wired
from `assets/` in `app.json`. The editorial mark's vector source is
`assets/icon.svg`; rasterize the variants with `rsvg-convert` (see the commit
that added the icon for the exact commands).

> **AdMob:** ads are free-first and fail closed — a banner only renders when
> `EXPO_PUBLIC_ADS_ENABLED="true"`, never for Pro users, and only with a real
> unit id. The `app.json` AdMob app IDs are currently Google's public **sample**
> IDs (valid, so native init never crashes, but they serve no live ads). Swap
> them for the owner's real AdMob app IDs before enabling ads.

| Variable | Purpose |
| --- | --- |
| `EXPO_PUBLIC_API_BASE` | Backend base URL, including `/api/v1`. Defaults to `http://localhost:8080/api/v1`. |
| `EXPO_PUBLIC_WAITLIST_MODE` | `0` opts into the full pilot UI; any other value (or unset) keeps waitlist mode on. |
| `EXPO_PUBLIC_WAITLIST_URL` | Absolute waitlist endpoint. Defaults to `https://menivor.com/api/waitlist`. |
| `EXPO_PUBLIC_APP_API_KEY` | Optional non-secret fallback key used when the user hasn't entered their own. |
| `EXPO_PUBLIC_REVENUECAT_IOS_API_KEY` | RevenueCat public, app-specific Apple SDK key. |
| `EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY` | RevenueCat public, app-specific Google SDK key. |
| `EXPO_PUBLIC_REVENUECAT_WEB_API_KEY` | Optional RevenueCat public web SDK key for the Expo web target. |
| `EXPO_PUBLIC_REVENUECAT_PRO_ENTITLEMENT_ID` | RevenueCat entitlement that unlocks export and sharing. Defaults to `pro`. |
| `EXPO_PUBLIC_SUPPORT_URL` | Public HTTPS help-center URL or `mailto:` link shown on the Support screen. |

`EXPO_PUBLIC_*` variables are inlined into the JS bundle at build time, so they
must not contain secrets. RevenueCat app-specific SDK keys are public by design;
RevenueCat secret API keys must remain server-side. The per-user API key entered
on the sign-in screen is the authenticated credential. The backend `/me.user_id`
is used as the RevenueCat App User ID so purchases follow the signed-in account.

Finished-video preview remains available to free users. Timeline export, trim
export, and public-link sharing refresh the RevenueCat customer state immediately
before performing the protected action. Missing, stale, expired, or unverifiable
entitlement state fails closed. Users can restore purchases from each export
surface. The account tab collects subscription management, support, privacy,
and same-installation device-account recovery in one place.

Finished exports are downloaded to durable app-owned device storage before the
iOS share sheet opens. The job detail keeps a local output receipt containing
the actual file path, byte size, media duration when reported, attempt count,
failure step, and share-sheet outcome. Retrying a share failure reuses the same
downloaded MP4; retrying a download keeps the same job and destination path.

The trends feed opens Diffusion Lab only from a durable trend observation. Each
forecast receives a caller-owned ID that is carried into compose/render params
and native publish telemetry. The Analytics forecast trace connects that trend,
forecast, render job, publish event, and creator-logged platform reach. Until a
`JobPerformance` row exists, reach and forecast delta remain unavailable and the
screen shows `veri bekleniyor` instead of treating missing data as zero.

## Project layout

```
apps/mobile/
├── app/                      # thin expo-router file-based route composition
│   ├── _layout.tsx           # root Stack + SessionProvider
│   ├── index.tsx             # sign-in / API-key entry
│   ├── (tabs)/
│   │   ├── _layout.tsx       # auth-gated tab navigator
│   │   ├── create.tsx        # exports the reel-create feature screen
│   │   ├── broll.tsx         # exports the B-roll feature screen
│   │   └── jobs.tsx          # exports the jobs-library screen
│   └── job/[id].tsx          # exports the job-detail feature screen
├── src/
│   ├── features/
│   │   ├── reel-create/      # form state, upload/create orchestration, UI
│   │   ├── broll-studio/     # durable history, foreground polling, attach
│   │   └── jobs-library/     # list/detail/retry and job presentation
│   └── shared/
│       ├── api/              # authenticated transport and error mapping
│       ├── auth/             # SecureStore-backed session abstraction
│       ├── theme/            # editorial design tokens (ink/paper/#FFD93D)
│       ├── product/          # waitlist client, drafts, product-mode, WaitlistHome
│       ├── billing/          # RevenueCat provider + entitlement policy
│       ├── lifecycle/        # AppState-aware cancellable polling primitives
│       ├── hooks/            # shared capability loaders
│       └── media/            # pickers, signed preview, local B-roll state
├── lib/
│   ├── api.ts                # endpoint methods + compatibility exports
│   ├── types.ts              # transitional feature exports over api-contract
│   └── feature clients       # domains not yet migrated into src/features
├── app.json                  # Expo config (expo-router, plugins, permissions)
├── babel.config.js           # babel-preset-expo
└── tsconfig.json             # strict TS + `@/*` path alias
```

## API client (`src/shared/api` + `lib/api.ts`)

Uses the same shared DTO and state semantics as web through
`@reelforge/api-contract`, while keeping Expo-specific upload and lifecycle code
local. Reel and B-roll creation send stable `Idempotency-Key` values across
ambiguous retries.
It unwraps the `{ status, data, message }` envelope and sends the secured
per-user credential as `x-api-key`.

Focused behaviour suites run without the optional native SDK installation:

```bash
npm run test:wallet    # wallet transfer client + journal
npm run test:product   # waitlist client, local drafts, product-mode gating
npm run test:billing   # entitlement policy
```

- `presignAndUpload(file, options)` — reserve an authenticated upload intent,
  stream it to R2 with `expo-file-system`, then finalize caller ownership.
- `createJob`, `getJob`, `listJobs`, `retryJob`
- `listAvatars`, `listVoices`, `me`
- `listPlans`, `createCheckout`
- canonical B-roll generate/list/poll/preset operations under
  `/generation/broll/*`
- `/pilot/capabilities` feature discovery shared by every first-party client

Because React Native has no `File` object, the upload path takes a `LocalFile`
`{ uri, name, mimeType, size }` (from the pickers) instead of the browser
`File` used by the web client — everything else is identical.
## Store onboarding

The default first launch calls `POST /api/v1/auth/device` with a random install
identifier kept in `expo-secure-store`. The server derives the account key with
`REELFORGE_DEVICE_AUTH_SECRET`, creates the account once, and grants the three
free signup credits. Existing API-key sign-in remains available as an advanced
path. The server secret must contain at least 32 characters; never expose it in
an `EXPO_PUBLIC_*` variable.
