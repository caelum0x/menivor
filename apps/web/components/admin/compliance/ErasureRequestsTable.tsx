"use client";

import { formatWhen } from "@/components/admin/format";
import { ErasureStatusBadge } from "@/components/admin/compliance/ErasureStatusBadge";
import type { ErasureRequest } from "@/lib/types";

interface ErasureRequestsTableProps {
  requests: readonly ErasureRequest[];
}

/**
 * Cross-tenant right-to-erasure request log (platform-admin only). READ-only:
 * every request across every tenant, newest first, with its lifecycle status and
 * timestamps. No PII is shown — only the target user id and the erasure scope.
 */
export function ErasureRequestsTable({ requests }: ErasureRequestsTableProps) {
  if (requests.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border py-12 text-center text-sm text-muted-foreground">
        No erasure requests have been made yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-secondary/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">User</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Scope</th>
            <th className="px-3 py-2 font-medium">Requested</th>
            <th className="px-3 py-2 font-medium">Completed</th>
          </tr>
        </thead>
        <tbody>
          {requests.map((r) => (
            <tr key={r.id} className="border-b border-border last:border-0">
              <td className="max-w-[14rem] truncate px-3 py-2 font-mono text-xs">
                {r.user_id}
              </td>
              <td className="px-3 py-2">
                <ErasureStatusBadge status={r.status} />
              </td>
              <td className="px-3 py-2 text-muted-foreground">{r.scope || "—"}</td>
              <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                {formatWhen(r.requested_at)}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                {formatWhen(r.completed_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
