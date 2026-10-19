import type {
  BaseRecord,
  DataProvider,
  GetListParams,
  GetListResponse,
} from "@refinedev/core";
import type { HttpError } from "@refinedev/core";
import {
  API_BASE,
  ApiError,
  adminListJobs,
  adminListUsers,
  adminListWorkspaces,
} from "@/lib/api";
import type {
  AdminJob,
  AdminListParams,
  AdminUser,
  AdminWorkspace,
} from "@/lib/types";

/** A token getter (the caller's Clerk JWT) for authenticating admin calls. */
export type TokenGetter = () => Promise<string | undefined>;

/**
 * The three platform-admin resources this provider serves, each mapped to its
 * typed, envelope-unwrapping fetcher in `lib/api`. Read-only: only `getList` is
 * meaningful (the admin surface lists cross-tenant rows; it never mutates them
 * through refine — impersonation is a separate explicit action).
 */
type AdminRow = AdminUser | AdminWorkspace | AdminJob;

const RESOURCE_FETCHERS: Record<
  string,
  (params: AdminListParams, options: { token?: string }) => Promise<AdminRow[]>
> = {
  users: (params, options) => adminListUsers(params, options),
  workspaces: (params, options) => adminListWorkspaces(params, options),
  jobs: (params, options) => adminListJobs(params, options),
};

/** Map any thrown error into refine's {@link HttpError} shape (keeps the status). */
function toHttpError(err: unknown): HttpError {
  if (err instanceof ApiError) {
    return { message: err.message, statusCode: err.status };
  }
  return {
    message: err instanceof Error ? err.message : "Request failed",
    statusCode: 0,
  };
}

const notImplemented = (op: string) => (): never => {
  throw new Error(
    `The platform-admin data provider is read-only; "${op}" is not supported.`,
  );
};

/**
 * A minimal, READ-ONLY refine {@link DataProvider} for the platform-admin
 * console, wrapping the typed `lib/api` admin fetchers (each of which unwraps the
 * backend envelope and is hard-gated on `is_staff` server-side). Pagination maps
 * refine's `currentPage`/`pageSize` to the backend's `offset`/`limit` (clamped
 * server-side). Because the endpoints return no total count, `total` is inferred
 * so that a FULL page enables "next" and a short page ends the list. Every
 * request carries the caller's Clerk JWT via `getToken`.
 */
export function createAdminDataProvider(getToken: TokenGetter): DataProvider {
  return {
    getApiUrl: () => API_BASE,

    getList: async <TData extends BaseRecord = BaseRecord>(
      params: GetListParams,
    ): Promise<GetListResponse<TData>> => {
      const { resource, pagination } = params;
      const fetcher = RESOURCE_FETCHERS[resource];
      if (!fetcher) {
        throw {
          message: `Unknown admin resource "${resource}".`,
          statusCode: 404,
        } satisfies HttpError;
      }

      const pageSize = pagination?.pageSize ?? 50;
      const currentPage = pagination?.currentPage ?? 1;
      const offset = (currentPage - 1) * pageSize;

      try {
        const token = await getToken();
        const rows = await fetcher({ limit: pageSize, offset }, { token });
        // No server-side count: infer a total that keeps paging correct — a full
        // page implies there may be more; a short page ends the list here.
        const total =
          rows.length === pageSize
            ? offset + rows.length + 1
            : offset + rows.length;
        return { data: rows as unknown as TData[], total };
      } catch (err) {
        throw toHttpError(err);
      }
    },

    // Read-only surface: the remaining DataProvider methods are intentionally
    // unsupported (the console never creates/updates/deletes admin rows).
    getOne: notImplemented("getOne"),
    create: notImplemented("create"),
    update: notImplemented("update"),
    deleteOne: notImplemented("deleteOne"),
  };
}
