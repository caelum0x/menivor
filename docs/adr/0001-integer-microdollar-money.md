# ADR 0001 — Integer microdollars for all money

**Status:** accepted

## Context
Floating-point money accumulates rounding error; per-second video pricing and
markup math compound it across reserve/settle/release.

## Decision
Represent all money as **integer microdollars** (1 USD = 1_000_000 micros). No
floats anywhere in the money path — wallet ledger, catalog prices, markup, payouts.
Formatting to `$x.xx` happens only at the display edge.

## Consequences
- Exact arithmetic; reservations always reconcile to zero.
- Prices are per-unit micros (image: per image; video: per second; audio: per clip).
- Cross-language helpers (`formatUsdMicros`) share the same integer math.
