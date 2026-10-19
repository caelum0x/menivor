# Data safety addendum (2026-10-06, after the signup-first build)

`DATA-SAFETY.md` in this folder was written for the earlier build. Changes since then, from the code:
- No device (guest) accounts any more: sign-in with Google (Android) is required, so Email address,
  Name and User IDs are **Required**, not optional.
- Social inbox, marketplace, team workspaces, media gateway and token transfers are not in the
  store build (dev-only, `src/shared/release/surface.ts`), so "Messages > Other in-app messages"
  and workspace member names no longer apply.
- AI processing consent is shown before first use (`src/shared/legal/AiProcessingConsent.tsx`).
The full current answers are in `../PRIVACY-ANSWERS.md`.
