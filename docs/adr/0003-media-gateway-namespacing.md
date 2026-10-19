# ADR 0003 — Namespace the media gateway under `/media`

**Status:** accepted

## Context
The OpenRouter-style media gateway first exposed `POST /api/v1/videos` and
`/api/v1/audio`. These **collided** with MoneyPrinterTurbo's legacy
`controllers/v1/video.py` endpoints at the same paths — FastAPI emitted a
"Duplicate Operation ID" warning and the gateway silently shadowed MPT's routes.
The `packages/api-contract` breaking-check surfaced it (envelope fields "removed").

## Decision
Namespace the **entire** gateway under `/api/v1/media/*`
(`/media/images`, `/media/videos`, `/media/audio`, `/media/credits`,
`/media/usage`, `/media/generation/{id}`), consistent with the pre-existing
`/media/models` + `/media/usage`.

## Consequences
- MPT's legacy `/videos` is restored; the gateway is purely additive.
- `REQUIRED_PATHS` in the contract enforces the `/media/*` surface.
- Rule: a new surface must never reuse a bare MPT path (`/videos`, `/audio`, …).
