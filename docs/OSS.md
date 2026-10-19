# Open source used by Menivor (Wave Q onward)

Every Wave Q package lists what it took from open source here: the repo, its
licence, the commit or version, and what was taken. MIT, Apache-2.0 and BSD
only for code we fork, port or vendor; AGPL only as an unmodified separate
server; never GPL in the mobile apps or in customer code. Older notices stay in
`THIRD_PARTY_NOTICES.md`.

| Package | Source | Licence | Version / commit | What was taken |
|---|---|---|---|---|
| QM1.0 | none | - | - | Glue only: the ad-event dedupe, SVOD refusal, invites, meter check and recount reuse the repo's own SQLAlchemy, rate limiter and Dodo client patterns. |
| QM1.1 | none | - | - | Data and glue only. Model ids and prices were read on 2026-09-30 from the vendors' own pages (OpenAI deprecations and model pages, Google Gemini pricing, fal model pages, MiniMax pay-as-you-go); sources are in the catalogue rows. |
| QM1.3 | expo/expo `packages/expo-web-browser` | MIT | 15.0.x (SDK 54 line; npm 15.0.11 checked 2026-10-05) | Dependency only: `openBrowserAsync` opens the creator's hosted checkout from the watch app. The discount body follows Dodo's public `POST /discounts` API reference (no code copied). |
| QM1.4 | qdrant/fastembed | Apache-2.0 | 0.8.1 (PyPI, checked 2026-10-05) | Dependency: `TextEmbedding("BAAI/bge-small-en-v1.5")` for discovery and related titles on the API and worker images; the hashing embedder stays the fallback. |
| QM1.4 | googlecast/CastReceiver | Apache-2.0 | `ddfb06c7fb94db902d7706f610553d8dd4ba85e7` | Ported the receiver page and the CAF LOAD-interceptor structure into `apps/watch/cast-receiver/` (notice kept); the token refresh and request rewrite are ours. |
| QM1.4 | react-native-google-cast | MIT | ^4.9.1 (already a dependency) | Sender side: `loadMedia` with `customData` for the Menivor receiver. |
| QM1.5 | expo/expo `packages/expo-notifications` | MIT | ~0.32.12 (npm 0.32.17 checked 2026-10-05) | Dependency only: viewer opt-in and the Expo push token in `apps/watch`; sending reuses the repo's own Expo push transport (`app/services/push.py`). Webhooks reuse the MN8 delivery and retry path. |
