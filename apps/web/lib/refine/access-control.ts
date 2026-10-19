import type { AccessControlProvider } from "@refinedev/core";
import { ApiError, adminListUsers } from "@/lib/api";
import type { TokenGetter } from "@/lib/refine/data-provider";

/**
 * Probe whether the caller is a PLATFORM ADMIN (`is_staff`). The platform-admin
 * endpoints are hard-gated on `is_staff` server-side and `is_staff` is NOT
 * exposed on `GET /me`, so the authoritative signal is the endpoints' own
 * response: a `200` means staff, a `403` means not staff. We probe the cheapest
 * one (`GET /admin/users?limit=1`). The result is cached per provider instance so
 * every `can` check reuses a single in-flight request.
 */
function makeStaffProbe(getToken: TokenGetter): () => Promise<boolean> {
  let cached: Promise<boolean> | null = null;
  return () => {
    if (cached) return cached;
    cached = (async () => {
      try {
        const token = await getToken();
        await adminListUsers({ limit: 1 }, { token });
        return true;
      } catch (err) {
        // A 403 is the definitive "not staff" signal. Any other error (401, 5xx,
        // network) is treated as "not staff" too — the console fails closed.
        if (err instanceof ApiError && err.status === 403) return false;
        return false;
      }
    })();
    return cached;
  };
}

/**
 * refine {@link AccessControlProvider} for the platform-admin console. The
 * `/admin/*` resources are gated on `is_staff` — deliberately SEPARATE from
 * workspace RBAC roles (a workspace `owner` is NOT a platform admin). `can`
 * therefore resolves to the staff probe for every admin resource/action. The
 * server independently enforces the same gate on every request; this only drives
 * whether refine renders the resource affordances.
 */
export function createAdminAccessControl(
  getToken: TokenGetter,
): AccessControlProvider {
  const isStaff = makeStaffProbe(getToken);
  return {
    can: async () => {
      const can = await isStaff();
      return {
        can,
        reason: can ? undefined : "Platform administrators only.",
      };
    },
    options: {
      buttons: { enableAccessControl: true, hideIfUnauthorized: true },
    },
  };
}
