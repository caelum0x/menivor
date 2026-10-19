# Menivor: privacy answers (App Store App Privacy + Play Data safety)

Read from the code on branch `mobile-fixall-2026-10-06` (apps/mobile), store build surface only
(`src/shared/release/surface.ts`). The owner enters the App Store answers in the ASC web UI
(App Privacy); the API cannot set them. Play answers go in Play Console > Data safety
(the existing `play/DATA-SAFETY.md` predates this build; see `play/DATA-SAFETY-ADDENDUM.md`).

## What the code does
- Sign-in is required: Sign in with Apple (`expo-apple-authentication`) or Google
  (`@react-native-google-signin`, loaded lazily), exchanged at Menivor's Scribase auth project
  (`src/shared/auth/*`), then `POST /auth/device` mints the Menivor session for that named account.
  A random install id (SecureStore) ties the session to the device. No guest accounts.
- All app traffic goes to `https://api.menivor.com/api/v1` (`src/shared/api/client.ts`).
- Purchases: RevenueCat (`react-native-purchases`) for Menivor Pro and consumable credit packs;
  the store transaction id is sent to the API to grant credits (`src/shared/billing/*`).
- Push: Expo push token registered with the API after the user allows notifications
  (`src/shared/notifications/usePushRegistration.ts`).
- Media: photo library and document picker for clips/images/audio (uploaded via presigned URLs),
  camera for a presenter selfie, microphone for a voice sample (`expo-image-picker`,
  `expo-document-picker`, `expo-av`).
- AI processing: prompts, links, scripts, clips, images, voice samples and selfies are sent to the
  Menivor API and processed by AI service providers (script writing, text to speech and voice
  cloning, presenter/lip-sync, b-roll and video generation, transcription for captions and dubbing).
  A one-time consent sheet explains this before the tabs are usable
  (`src/shared/legal/AiProcessingConsent.tsx`, App Store 5.1.2(i)); it is recorded locally and as
  consent kind `ai_processing` server-side (best effort).
- Not present: ads SDKs, analytics SDKs, crash reporting SDKs, location, contacts, health, IDFA/ATT.
  `NSPrivacyTracking` is false in app.json.

## App Store Connect > App Privacy
Tracking: **No** (no data is used for tracking; no data broker sharing).

| Data type | Collected | Linked to user | Tracking | Purposes |
|---|---|---|---|---|
| Contact Info > Email Address | Yes (from Apple/Google; may be an Apple private relay address) | Yes | No | App Functionality |
| Contact Info > Name | Yes (Apple/Google profile name, when shared) | Yes | No | App Functionality |
| User Content > Photos or Videos | Yes (clips, images, selfie for presenter, rendered reels) | Yes | No | App Functionality |
| User Content > Audio Data | Yes (voice sample for a narrator voice, audio uploads) | Yes | No | App Functionality |
| User Content > Other User Content | Yes (prompts, links, scripts, captions, brand settings) | Yes | No | App Functionality |
| Identifiers > User ID | Yes (Menivor account id, install id) | Yes | No | App Functionality |
| Identifiers > Device ID | Yes (Expo push token, only after permission) | Yes | No | App Functionality |
| Purchases > Purchase History | Yes (Pro subscription, credit packs) | Yes | No | App Functionality |
| Usage Data, Diagnostics, Location, Health, Contacts, Browsing, Search, Financial Info (cards), Sensitive Info | No | | | |

Notes for the owner:
- The privacy policy at https://menivor.com/privacy must name the AI processing (what is sent,
  to which kinds of providers, retention) to match the consent sheet.
- Voice samples and selfies are used to create the user's own voice/presenter; they are deletable
  in Account > Voices / Presenters and with account deletion.

## Google Play > Data safety
- Data is encrypted in transit: Yes (HTTPS only).
- Users can request deletion: Yes, in app (Account > Privacy and data > Delete account).
  A web deletion page is still needed for the Play form: `https://menivor.com/account/delete`
  answers 404 today (owner: publish one, or point to the privacy page section).
- Shared with third parties: No for "sharing" in Play's sense (AI providers act as service
  providers/processors on Menivor's behalf).

| Play category | Type | Collected | Optional | Purposes |
|---|---|---|---|---|
| Personal info | Email address, Name | Yes | Required (sign-in) | App functionality, Account management |
| Personal info | User IDs | Yes | Required | App functionality, Account management |
| Financial info | Purchase history | Yes | Optional (only buyers) | App functionality |
| Photos and videos | Photos, Videos | Yes | Optional | App functionality |
| Audio | Voice or sound recordings, Other audio files | Yes | Optional | App functionality |
| Files and docs | Files and docs | Yes | Optional | App functionality |
| App activity | Other user-generated content (prompts, scripts, links) | Yes | Required to create | App functionality |
| Device or other IDs | Push token | Yes | Optional | App functionality |
