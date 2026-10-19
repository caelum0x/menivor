/**
 * API base-URL resolution, split out of `client.ts` so modules the client
 * itself depends on (e.g. the device-session store) can import it without a
 * circular dependency.
 *
 * `NEXT_PUBLIC_*` vars are inlined into the bundle at `next build` time (both
 * the client JS and the server/SSR code paths) — the `vars` block in
 * `wrangler.jsonc` only sets the Workers *runtime* environment and does not
 * affect what already got baked into a build that ran without this var set.
 * A production build that is missing `NEXT_PUBLIC_API_BASE` must never
 * silently ship the local-dev default: every billing, catalog and
 * payments-mode fetch from a real visitor's browser (and every SSR render)
 * would then try `http://localhost:8080`, fail with
 * `ERR_CONNECTION_REFUSED`, and leave every CTA on /pricing permanently
 * disabled with no error surfaced anywhere — a checkout outage with no
 * signal. Fall back to the known production API host in that case instead of
 * localhost.
 */

const DEV_DEFAULT_API_BASE = "http://localhost:8080/api/v1";
const PRODUCTION_API_BASE = "https://api.menivor.com/api/v1";

/** Pure resolver (unit-tested directly, without mutating `process.env`). */
export function resolveApiBase(
  configured: string | undefined,
  nodeEnv: string | undefined,
): string {
  const trimmed = (configured || "").trim();
  if (trimmed) return trimmed.replace(/\/+$/, "");
  return nodeEnv === "production" ? PRODUCTION_API_BASE : DEV_DEFAULT_API_BASE;
}

export const API_BASE: string = resolveApiBase(
  process.env.NEXT_PUBLIC_API_BASE,
  process.env.NODE_ENV,
);
