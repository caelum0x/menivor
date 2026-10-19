"use client";

import { formatWhen } from "@/components/admin/format";
import type { RetentionPolicy } from "@/lib/types";

interface RetentionOverviewTableProps {
  policies: readonly RetentionPolicy[];
}

/** Render a retention window: a day count, or "Keep forever" when unset (null). */
function windowLabel(days: number | null): string {
  return days === null ? "Keep forever" : `${days} day${days === 1 ? "" : "s"}`;
}

/**
 * Cross-tenant retention-posture overview (platform-admin only). READ-only: every
 * configured workspace retention policy, so an operator can audit which tenants
 * have jobs/assets windows set versus keep-forever.
 */
export function RetentionOverviewTable({
  policies,
}: RetentionOverviewTableProps) {
  if (policies.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border py-12 text-center text-sm text-muted-foreground">
        No workspace has configured a retention policy yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-secondary/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">Workspace</th>
            <th className="px-3 py-2 font-medium">Jobs retention</th>
            <th className="px-3 py-2 font-medium">Assets retention</th>
            <th className="px-3 py-2 font-medium">Updated</th>
          </tr>
        </thead>
        <tbody>
          {policies.map((p) => (
            <tr
              key={p.workspace_id}
              className="border-b border-border last:border-0"
            >
              <td className="max-w-[14rem] truncate px-3 py-2 font-mono text-xs">
                {p.workspace_id}
              </td>
              <td className="px-3 py-2 tabular-nums">
                {windowLabel(p.jobs_retention_days)}
              </td>
              <td className="px-3 py-2 tabular-nums">
                {windowLabel(p.assets_retention_days)}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                {formatWhen(p.updated_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
