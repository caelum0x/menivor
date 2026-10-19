"use client";

import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { AuditEntry } from "@/lib/types";

/** Turn an action slug like `members.role_changed` into "Members · role changed". */
function humanizeAction(action: string): string {
  const [group, ...rest] = action.split(".");
  const detail = rest.join(".").replace(/_/g, " ");
  const head = group ? group.charAt(0).toUpperCase() + group.slice(1) : action;
  return detail ? `${head} · ${detail}` : head;
}

/** Best-effort locale timestamp; falls back to the raw value. */
function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** Compact one-line summary of an entry's metadata (e.g. role transitions). */
function summarizeMeta(meta: Record<string, unknown>): string {
  if (meta.old_role && meta.new_role) {
    return `${String(meta.old_role)} → ${String(meta.new_role)}`;
  }
  const keys = Object.keys(meta);
  if (keys.length === 0) return "";
  return keys
    .slice(0, 3)
    .map((k) => `${k}: ${String(meta[k])}`)
    .join(", ");
}

export interface AuditLogTableProps {
  loading: boolean;
  entries: readonly AuditEntry[];
}

/** Read-only, tenant-scoped audit-trail table (newest first). */
export function AuditLogTable({ loading, entries }: Readonly<AuditLogTableProps>) {
  if (loading) {
    return (
      <div className="space-y-2" aria-busy>
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        No audit activity on this page.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border bg-secondary/40 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">When</th>
            <th className="px-3 py-2 font-medium">Action</th>
            <th className="px-3 py-2 font-medium">Actor</th>
            <th className="px-3 py-2 font-medium">Target</th>
            <th className="px-3 py-2 font-medium">Detail</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const detail = summarizeMeta(entry.metadata ?? {});
            return (
              <tr key={entry.id} className="border-b border-border last:border-b-0">
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                  {formatWhen(entry.created_at)}
                </td>
                <td className="px-3 py-2">
                  <Badge variant="secondary">{humanizeAction(entry.action)}</Badge>
                </td>
                <td className="max-w-[10rem] truncate px-3 py-2 font-mono text-xs">
                  {entry.actor_user_id}
                </td>
                <td className="max-w-[10rem] truncate px-3 py-2 font-mono text-xs">
                  {entry.target_id ?? "—"}
                </td>
                <td className="px-3 py-2 text-muted-foreground">{detail || "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
