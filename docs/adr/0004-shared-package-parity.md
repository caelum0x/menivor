# ADR 0004 — TS↔Python parity for shared logic packages

**Status:** accepted

## Context
The client (web/mobile) and the Python backend must compute identical numbers for
previews vs. renders (captions, filtergraphs, kernels, trend scores, hook gates).
Duplicated logic drifts.

## Decision
Shared-logic packages ship a TypeScript port **and** a Python port with a **golden
fixture** contract: the Python side generates the golden, both ports are asserted
against it (`test_parity.py` + a compiled-TS `parity.mjs`), and a matrix CI job runs
both. Parity is guaranteed by using only deterministic primitives:
- pure polynomial / integer math (no float transcendentals) for kernels;
- a shared `round6` (truncate half-away-from-zero) for float scores;
- FNV-1a-32 over an integer/string canonical form for content hashes;
- byte-identical string assembly for ASS / filtergraph output.

## Consequences
- 10 of the 13 shared packages carry byte/bit-identical cross-language parity.
- React-only packages (`ui-kit`) and stateful HTTP clients are exempt (no shared logic).
