"use client";

import { Badge } from "@/components/ui/badge";
import { ResourceTable, type Column } from "@/components/admin/ResourceTable";
import { formatWhen, jobStateLabel } from "@/components/admin/format";
import type { AdminJob } from "@/lib/types";

const COLUMNS: readonly Column<AdminJob>[] = [
  {
    key: "id",
    header: "Job",
    render: (j) => j.id,
    className: "max-w-[12rem] truncate px-3 py-2 font-mono text-xs",
  },
  {
    key: "user_id",
    header: "User",
    render: (j) => j.user_id,
    className: "max-w-[12rem] truncate px-3 py-2 font-mono text-xs",
  },
  {
    key: "kind",
    header: "Kind",
    render: (j) => j.kind ?? "—",
    className: "px-3 py-2 text-muted-foreground",
  },
  {
    key: "state",
    header: "State",
    render: (j) => <Badge variant="secondary">{jobStateLabel(j.state)}</Badge>,
  },
  {
    key: "progress",
    header: "Progress",
    render: (j) => (typeof j.progress === "number" ? `${j.progress}%` : "—"),
    className: "px-3 py-2 tabular-nums",
  },
  {
    key: "created_at",
    header: "Created",
    render: (j) => formatWhen(j.created_at),
    className: "whitespace-nowrap px-3 py-2 text-muted-foreground",
  },
];

/** Cross-tenant job directory (platform-admin only). */
export default function AdminJobsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Jobs</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every reel job across all tenants.
        </p>
      </div>
      <ResourceTable<AdminJob> resource="jobs" columns={COLUMNS} />
    </div>
  );
}
