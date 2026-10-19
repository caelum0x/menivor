# OpenCut editor module

This directory preserves the former OpenCut editor source while it is migrated
into the ReelForge Next.js runtime. It is intentionally not a Vite workspace or
deployable. Its former Elysia worker is retained in `../editor-bff` only as a
narrow editor adapter; it must not own product data or persistence.

The active product implementation now lives in `../src/features/editor` and is
composed by `../app/editor/page.tsx`. The preserved route in this directory was
only a “Coming soon” screen; do not add product behavior here. Generic UI files
may be migrated selectively when the active feature needs them.
