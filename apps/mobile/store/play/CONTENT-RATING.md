# Play Console: IARC content rating questionnaire (Menivor)

Category to choose: **All other app types** (not a game, not a reference/news app).

| Question | Answer |
|---|---|
| Violence | No. The app has no violent content of its own. Users generate videos with AI models; see the generative AI note below |
| Blood | No |
| Sexuality or nudity | No. The app does not offer or advertise adult content |
| Language (profanity, crude humour) | No |
| Controlled substances | No |
| Gambling (real or simulated) | No. Credits buy generation only; there are no random rewards |
| Fear or horror | No |
| Users can interact or exchange content | **Yes**. Public creator profiles and leaderboard (`app/creator/[id].tsx`, `app/leaderboard.tsx`), a public template marketplace with ratings and cloning (`app/marketplace.tsx`), team workspaces with members and approvals (`app/team.tsx`, `app/approvals.tsx`), and credit transfers to another user's handle (`app/wallet/transfer.tsx`) |
| Shares user location | No. The app requests no location permission (`app.json` android.permissions) |
| Allows purchases of digital goods | **Yes**. Plans and credit packs through RevenueCat (`src/shared/billing/revenuecat-adapter.ts`); store builds do not open the hosted web checkout (`app/wallet/top-up.tsx`, `app/wallet/plans.tsx`) |
| Unrestricted internet or web browser | No. The in-app browser opens only Menivor pages, legal documents and sign-in flows (`expo-web-browser`) |
| Is it a web browser or search engine | No |
| Is it primarily news or educational | No |

Expected result: a low age rating (IARC 3+ / ESRB Everyone range) with the interactive elements
"Users Interact" and "In-App Purchases". The exact rating is assigned by IARC. The target audience
is set separately to 18+ (see DATA-SAFETY.md).

Generative AI note: Play's AI-generated content policy requires a way to report or flag offensive
AI output inside the app. A search of `app/`, `src/`, `lib/` and `components/` found no report or
flag action on generated results. BLOCKER: add a "Report this result" action (job result screen and
B-roll/media gateway output) that reaches support before applying for production.
