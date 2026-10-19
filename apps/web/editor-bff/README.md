# ReelForge editor BFF

This Cloudflare Worker is an optional, stateless transport seam for the native
ReelForge web editor. It is not a product backend.

The authoritative product API, authentication, authorization, projects, jobs,
assets, and media ownership remain in `apps/api` under `/api/v1`. Until an
editor-specific transport is implemented, `/capabilities` intentionally
advertises an empty transport list so clients cannot mistake this scaffold for
a persistence service.

Do not add generic proxy, authentication, storage, or generation routes here.
Any future endpoint must be scoped to editor transport (for example a realtime
collaboration channel) and must delegate identity and durable state to the
ReelForge API.
