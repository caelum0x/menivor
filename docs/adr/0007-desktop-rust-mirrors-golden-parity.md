# ADR 0007 — Desktop Rust mirrors of shared packages, with 3-way golden parity

**Status:** accepted

## Context
Eight shared pure-logic packages ([ADR 0004](0004-shared-package-parity.md)) carry
byte/bit-identical TS↔Python golden parity: `trends-schema`, `growth-analytics`,
`caption-engine`, `shot-template-schema`, `effects-core`, `provider-adapter-kit`,
`comfy-workflow-schema`, `render-core`. The native desktop app (GPUI/Rust) previously
had no access to this logic — it could not score a trend, gate a hook, build a caption,
pin a workflow, apply an effect kernel, or build a filtergraph the way the
web/mobile/API surfaces do, so a desktop page either duplicated logic (drift risk) or
couldn't exist.

## Decision
Each shared pure-logic package gets a **Rust mirror crate** under
`apps/desktop/crates/rf-*`, making parity a **3-way guarantee (TS = Python = Rust)**:

| Package | Desktop crate |
|---|---|
| trends-schema | `rf-trends` |
| growth-analytics | `rf-growth` |
| caption-engine | `rf-captions` |
| shot-template-schema | `rf-shots` |
| effects-core | `rf-effects` |
| provider-adapter-kit | `rf-provider` |
| comfy-workflow-schema | `rf-workflows` |
| render-core | `rf-render-core` |

Composable engine crates then chain these primitives into real operations:
`rf-insights` (analytics → post/rework verdict), `rf-preflight` (license+cost →
clearance), `rf-plan` → `rf-compose`+`rf-audio` → `rf-render-cmd` (blueprint → the full
`ffmpeg` argv), all behind the `rf-runtime` facade.

Rules:
- **Same deterministic primitives** as ADR 0004: integer math where the source uses it,
  a shared `round6` (truncate half-away-from-zero) for float scores, FNV-1a over the same
  canonical byte order for content hashes, byte-identical string assembly.
- **Parity is asserted against the *package's own* golden fixtures**, not re-derived:
  each crate ships `tests/parity.rs` that reads `packages/<pkg>/test/fixtures/golden/*.json`
  (the exact vectors the TS + Python are validated against) via a `CARGO_MANIFEST_DIR`-relative
  path and asserts the Rust output matches every case. **176 golden cases across the 7 crates.**
- **CI-enforced** by the existing `desktop-crates` job (`.github/workflows/vision2026-ci.yml`):
  `cargo test --workspace --exclude reelforge-desktop` + `clippy -D warnings` + `fmt --check`.
  The workspace `members` is a glob (`apps/desktop/crates/*`) so a new crate auto-registers.
- **Pure crates only.** These are `#[cfg(test)]`-verifiable with no GPU/network/Metal — they
  compile and test on stock CI, unlike the GPUI binary (which needs the platform Metal
  toolchain and is excluded).

## Consequences
- Desktop pages can render the identical numbers/structures the pipeline uses, provably —
  the shot structure, caption style, hook gate, reach tier, trend opportunity, effect
  transform, and workflow pin a creator sees on desktop equal what the renderer/scorer uses.
- The desktop engine grew from 17 crates / 138 tests to **31 crates / 334 tests**, with
  0 clippy warnings and 0 fmt drift.
- The render command is **hardware-aware**: `rf-render-cmd::build_render_argv_hw`
  (and its `rf-runtime::render_command_hw` facade) selects the host's best GPU H.264
  encoder via `rf-hardware::select_encoder` (VideoToolbox / NVENC / QSV / VAAPI / AMF,
  targeting `-b:v`), falling back byte-for-byte to the software `build_render_argv`
  (`libx264 -crf 21`) when the box has no hardware encoder — the same policy `rf-encode`
  and the cloud renderer use.
- Pinning the ports to their spec **found and fixed real bugs** the crates' own tests
  missed: `rf-jobs` (missing `normalize` aliases NOT_STARTED/DONE/FAILURE/TIMEOUT; and
  `transition` overriding an explicit `progress` on COMPLETED, vs `envelope.py`'s
  arg-first precedence) and `rf-ffmpeg` (`fmt_chroma` needed a real `%.4g`, not Rust's
  shortest-Display, to match `compose_ffmpeg.py` beyond 4 significant figures). Older
  crates that mirror `apps/api` Python now ship `tests/py_parity.rs` pinning that behavior.
- The port work parallelizes safely (each crate is an isolated directory) and is fully
  machine-verifiable, so it was built with worktree-isolated multi-agent workflows and each
  claim re-run independently — see also [ADR 0006](0006-desktop-engine-pure-core-boundary.md)
  for the pure-core boundary these crates follow.
- Adding a new shared package to desktop is now a mechanical port + a golden-fixture parity
  test, not a re-implementation.
