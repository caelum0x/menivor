/**
 * Typed client for the PLATFORM-ADMIN compliance surface — Expo mirror of the
 * backend `app/controllers/v1/admin_compliance.py`. These three endpoints round
 * out the admin fetchers that already live in `lib/api.ts`
 * (`adminListUsers` / `adminListWorkspaces` / `adminListJobs` / `adminImpersonate`)
 * and `lib/billing.ts` (`getRevenue`).
 *
 * SECURITY / SCOPE
 *  - Every route here is HARD-GATED on the platform `is_staff` flag server-side
 *    (a workspace owner is NOT staff). A non-staff caller receives a 403
 *    {@link ApiError}; the client never grants access — it only renders whatever
 *    the server chooses to return.
 *  - Auth flows through the shared `x-api-key` transport via the session token;
 *    no secrets live in this module.
 *  - `POST /admin/erasure/{user_id}` ANONYMIZES the target's PII in place
 *    (irreversible) while preserving legally-required financial/audit records —
 *    it never cascade-deletes. Always confirm before calling it.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";
import type { AdminListParams } from "@/lib/types";
import type { ErasureRequest } from "@/lib/compliance";

/** Server + client cap on a platform-admin listing page (`limit`). */
export const MAX_ADMIN_COMPLIANCE_LIMIT = 200;
/** Default platform-admin listing page size requested by the client. */
export const DEFAULT_ADMIN_COMPLIANCE_LIMIT = 50;

/**
 * A single workspace's data-retention window in the cross-tenant overview
 * (GET /admin/retention). A `null` day-count means "keep forever" for that
 * dimension (it is never swept). Platform-admin (`is_staff`) only.
 */
export interface RetentionPolicy {
  /** The workspace the policy belongs to. */
  workspace_id: string;
  /** Days jobs are kept before the sweep anonymizes them; `null` = keep forever. */
  jobs_retention_days: number | null;
  /** Days assets are kept before the sweep anonymizes them; `null` = keep forever. */
  assets_retention_days: number | null;
  /** ISO-8601 timestamp the policy was created, when available. */
  created_at: string | null;
  /** ISO-8601 timestamp the policy was last updated, when available. */
  updated_at: string | null;
}

/** Shared page-window query builder (clamped `[1,200]` / `>= 0`). */
function adminListQuery(params: AdminListParams): string {
  const query = new URLSearchParams();
  if (typeof params.limit === "number" && Number.isFinite(params.limit)) {
    query.set(
      "limit",
      String(Math.min(MAX_ADMIN_COMPLIANCE_LIMIT, Math.max(1, Math.trunc(params.limit)))),
    );
  }
  if (typeof params.offset === "number" && Number.isFinite(params.offset)) {
    query.set("offset", String(Math.max(0, Math.trunc(params.offset))));
  }
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

/**
 * GET /admin/erasure-requests — every right-to-erasure request across every
 * tenant (newest first). PLATFORM-ADMIN ONLY (403 for non-staff). The backend
 * returns the list under `data`; a `{ erasure_requests: [...] }` wrapper is
 * tolerated for forward-compat.
 */
export async function adminListErasureRequests(
  params: AdminListParams = {},
  options?: RequestOptions,
): Promise<ErasureRequest[]> {
  const data = await request<
    ErasureRequest[] | { erasure_requests?: ErasureRequest[] }
  >(`/admin/erasure-requests${adminListQuery(params)}`, { options });
  if (Array.isArray(data)) return data;
  return data?.erasure_requests ?? [];
}

/**
 * GET /admin/retention — the cross-tenant retention-policy overview (every
 * configured workspace policy). PLATFORM-ADMIN ONLY (403 for non-staff). The
 * backend returns the list under `data`; a `{ policies: [...] }` wrapper is
 * tolerated for forward-compat. This endpoint is not paginated server-side.
 */
export async function adminListRetention(
  options?: RequestOptions,
): Promise<RetentionPolicy[]> {
  const data = await request<
    RetentionPolicy[] | { policies?: RetentionPolicy[] }
  >("/admin/retention", { options });
  if (Array.isArray(data)) return data;
  return data?.policies ?? [];
}

/**
 * POST /admin/erasure/{user_id} — operator-initiated erasure of a target user.
 * PLATFORM-ADMIN ONLY (403 for non-staff; unknown target 400). Anonymizes the
 * target's PII in place and revokes their credentials while preserving
 * financial/audit records; an append-only audit row records THIS operator as the
 * actor. IRREVERSIBLE — always confirm with the operator first. Returns the
 * resulting {@link ErasureRequest}.
 */
export function adminEraseUser(
  userId: string,
  options?: RequestOptions,
): Promise<ErasureRequest> {
  return request<ErasureRequest>(
    `/admin/erasure/${encodeURIComponent(userId)}`,
    { method: "POST", options },
  );
}
