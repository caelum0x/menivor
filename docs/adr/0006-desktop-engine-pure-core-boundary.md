# ADR 0006 — Desktop engine: pure cores, injected transport

**Status:** accepted

## Context
The desktop app is a local render farm + ComfyUI bridge + clipfarm operator + offline
project store (see [apps-desktop.md](../reelforge/vision2026/architecture/apps-desktop.md)).
Its logic must be deterministic and unit-testable without a GPU, a network, or the
GPUI shell — but it also must *compose* into coherent operations the UI and the
on-device MCP daemon call. A hardening pass over the `rf-*` crates surfaced a
recurring shape worth pinning down as a decision.

## Decision
Every engine crate is a **pure core**: it owns policy/format/decision logic as
plain functions + value types, and the actual I/O (GPU calls, HTTP, node transport,
FFmpeg exec, blob writes) is an **injected boundary** — a trait or a `now`/handle
parameter — supplied by the runtime/app layer.

- **Pure decision crates** (`rf-render` lease scheduler, `rf-sync` reconcile,
  `rf-comfy` VRAM pool, `rf-clipfarm` fan-out, `rf-jobs` envelope): take `now`,
  task lists, and budgets; return leases/plans/decisions. No clock, no sockets.
- **Pure argv/graph builders** (`rf-encode`, `rf-capture`, `rf-ffmpeg`,
  `rf-gateway` request bodies): assemble strings/vectors; the runtime spawns them.
- **Trait seams for real I/O**: `rf-assets::BlobStore` (persist/delete bytes),
  `rf-plugins` capability allowlist (host supplies the approved set),
  `rf-devproto` (runtime dispatches the validated request).
- **`rf-runtime` is the only composer**: it wires the pure cores into operations
  (`submit_project`, `report_progress`/`complete_job`/`fail_job`, `plan_clipfarm`)
  and holds the small amount of session state (job envelopes, seen-hashes). It
  uses the job-aware scheduling path so a terminal shot is never re-leased, and
  heartbeats leases on progress so long renders aren't reclaimed mid-flight.

Invariants enforced by the pass:
- Integer math where a value crosses a surface (µ-dollars, ms, per-mille speed) —
  no floats in content-addressed or duration paths.
- A declared dependency must be *used*; an unused crate dep is a defect (it hides
  an unwired composition, as with the render↔jobs and runtime↔clipfarm gaps).
- A doc claim must match behavior (e.g. `watermark_free`, the `BlobStore` trait,
  the clipfarm parity note were all corrected to match the code).

## Consequences
- The whole engine is testable with `cargo test` and no environment: 138 pure-lib
  unit tests (`cargo test --workspace --exclude reelforge-desktop`), deterministic,
  no GPU/network/Metal needed. Only the top-level GPUI binary requires the platform
  toolchain. CI gates test + `clippy -D warnings` + `cargo fmt --check` on this set
  (`.github/workflows/vision2026-ci.yml` → `desktop-crates`).
- Swapping transport (local vs. LAN node, on-disk vs. R2 blobs) never touches core
  logic — it's a different trait impl injected at the app layer.
- Cross-surface parity holds by construction: the same integer/string builders
  (`rf-ffmpeg` chromakey/ass/vstack, `rf-gateway` cost) mirror the Python renderer.
