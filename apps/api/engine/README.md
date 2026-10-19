# ReelForge generation engine

This directory is a backend-owned GPU capability, not a second product API.
Only generation workers may import it. Web, mobile, desktop, the public FastAPI
process, and code under `external/` never import this source directly.

The stable integration surface is `reelforge_engine`:

- `GenerationRequest` is the immutable, validated worker-to-engine request;
- `GenerationResult` is the engine-to-worker result and contains no database,
  credit, authentication, or public-response concerns;
- `get_pipeline()` resolves only product-registered inference paths.

Model weights live outside Git and are selected by deployment configuration.
The existing flat engine modules remain migration internals. New product code
must not add more `sys.path` manipulation or import those modules directly.

`external/` projects are research/vendor checkouts. Their code may only enter a
runtime through a separately approved, pinned image or product-owned HTTPS
adapter recorded in `external/REGISTRY.md`.
