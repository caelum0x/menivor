# ADR 0002 — Success-only billing

**Status:** accepted

## Context
A generation can fail upstream after we've reserved the customer's funds. Charging
for a non-delivered output is a trust and refund liability.

## Decision
**Reserve** on submit, **settle** the actual on success, **release** (full refund)
on failure. A failed job nets **zero**. A cataloged provider with a missing key
returns **503 + refund** (honest degradation) rather than faking a result.

## Consequences
- The render executor + media gateway emit `wallet_debit_micros{reason}` only on
  success, paired with a completed-job counter.
- A paging invariant fires if a debit has no matching completed job in the window
  (see `infra/observability/slo.yaml`).
