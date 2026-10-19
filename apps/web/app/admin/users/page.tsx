"use client";

import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { ResourceTable, type Column } from "@/components/admin/ResourceTable";
import { ImpersonateButton } from "@/components/admin/ImpersonateButton";
import { formatWhen } from "@/components/admin/format";
import type { AdminUser } from "@/lib/types";

const COLUMNS: readonly Column<AdminUser>[] = [
  {
    key: "email",
    header: "Email",
    render: (u) => (
      <span className="font-medium">{u.email ?? "—"}</span>
    ),
  },
  {
    key: "display_name",
    header: "Name",
    render: (u) => u.display_name ?? "—",
    className: "px-3 py-2 text-muted-foreground",
  },
  {
    key: "is_staff",
    header: "Staff",
    render: (u) =>
      u.is_staff ? <Badge variant="success">Staff</Badge> : <span>—</span>,
  },
  {
    key: "credits",
    header: "Credits",
    render: (u) => u.credits,
    className: "px-3 py-2 tabular-nums",
  },
  {
    key: "created_at",
    header: "Joined",
    render: (u) => formatWhen(u.created_at),
    className: "whitespace-nowrap px-3 py-2 text-muted-foreground",
  },
];

/** Cross-tenant user directory (platform-admin only) with an impersonate action. */
export default function AdminUsersPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Users</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every user across all tenants. Impersonation mints a short-lived,
          audited token.
        </p>
      </div>
      <ResourceTable<AdminUser>
        resource="users"
        columns={COLUMNS}
        renderActions={(u) => (
          <ImpersonateButton userId={u.id} label={u.email ?? u.id} />
        )}
      />
    </div>
  );
}
