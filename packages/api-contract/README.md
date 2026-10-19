# `@reelforge/api-contract`

The versioned client contract for ReelForge's public `/api/v1` API.

- `openapi/reelforge-v1.json` is exported from the real FastAPI application.
- `src/generated/reelforge-v1.ts` is generated from its component schemas.
- `src/job-state.ts`, `src/errors.ts`, and `src/capabilities.ts` contain stable,
  reviewed client semantics that OpenAPI alone cannot express.

Regenerate after an API schema change:

```sh
npm --workspace @reelforge/api-contract run contract:export
```

Check that committed artifacts are current:

```sh
npm --workspace @reelforge/api-contract run contract:check
npm --workspace @reelforge/api-contract run typecheck
```

The export fails if required canonical routes disappear or if the historical
mis-prefixed `/generation/api/*` B-roll route returns.

The check also compares the current schema with the reviewed
`openapi/reelforge-v1.baseline.json`. It rejects removed paths or methods,
newly-required request fields and parameters, removed or narrowed response
fields, enum/type narrowing, removed media/status variants, and authentication
scheme changes.

Normal generation never advances the baseline. After an intentionally breaking
release completes its approved deprecation process, update it explicitly:

```sh
npm run contract:baseline
```
