"use client";

import { ResourceTable, type Column } from "@/components/admin/ResourceTable";
import { formatWhen } from "@/components/admin/format";
import type { AdminWorkspace } from "@/lib/types";

const COLUMNS: readonly Column<AdminWorkspace>[] = [
  {
    key: "name",
    header: "Name",
    render: (w) => <span className="font-medium">{w.name ?? "—"}</span>,
  },
  {
    key: "id",
    header: "ID",
    render: (w) => w.id,
    className: "max-w-[12rem] truncate px-3 py-2 font-mono text-xs",
  },
  {
    key: "owner_id",
    header: "Owner",
    render: (w) => w.owner_id,
    className: "max-w-[12rem] truncate px-3 py-2 font-mono text-xs",
  },
  {
    key: "created_at",
    header: "Created",
    render: (w) => formatWhen(w.created_at),
    className: "whitespace-nowrap px-3 py-2 text-muted-foreground",
  },
];

/** Cross-tenant workspace directory (platform-admin only). */
export default function AdminWorkspacesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Workspaces</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every workspace across all tenants.
        </p>
      </div>
      <ResourceTable<AdminWorkspace> resource="workspaces" columns={COLUMNS} />
    </div>
  );
}
