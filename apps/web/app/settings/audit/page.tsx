"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight, RefreshCw, ScrollText } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { WorkspacePicker } from "@/components/settings/WorkspacePicker";
import { AuditLogTable } from "@/components/settings/AuditLogTable";
import { useAuditLog } from "@/components/settings/use-audit-log";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";

/**
 * ENTERPRISE — Audit log (settings/audit). A paginated, read-only view of a
 * workspace's APPEND-ONLY audit trail. Requires the caller to hold `audit.read`
 * (admin/owner); a caller without it sees a clear "not authorized" state rather
 * than another tenant's rows. Strictly tenant-scoped — only the selected
 * workspace's activity is ever shown.
 */
export default function AuditSettingsPage() {
  const { status: wsStatus, workspaces, errorMessage: wsError } =
    useMyWorkspaces();

  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  React.useEffect(() => {
    const first = workspaces[0];
    if (!first) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!workspaces.some((w) => w.id === selectedId)) setSelectedId(first.id);
  }, [workspaces, selectedId]);

  const audit = useAuditLog(selectedId);
  const forbidden = audit.status === "error" && audit.errorStatus === 403;

  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/audit" />

      <section className="container py-10">
        <div className="mx-auto max-w-4xl space-y-6">
          <div>
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <ScrollText className="size-7 text-primary" aria-hidden />
              Audit log
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              An append-only record of governance events (role changes,
              impersonation, …) for this workspace. Read-only and tamper-evident.
            </p>
          </div>

          {wsStatus === "error" ? (
            <Card>
              <CardContent className="py-8 text-sm text-destructive" role="alert">
                {wsError}
              </CardContent>
            </Card>
          ) : wsStatus === "ready" && workspaces.length === 0 ? (
            <Card className="border-dashed">
              <CardContent className="py-16 text-center text-sm text-muted-foreground">
                You don&apos;t belong to any workspace yet.
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <CardTitle>Activity</CardTitle>
                    <CardDescription>Newest events first.</CardDescription>
                  </div>
                  <div className="flex items-end gap-2">
                    <WorkspacePicker
                      workspaces={workspaces}
                      selectedId={selectedId}
                      onSelect={setSelectedId}
                      disabled={audit.status === "loading"}
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={audit.reload}
                      disabled={audit.status === "loading"}
                    >
                      <RefreshCw
                        className={
                          audit.status === "loading"
                            ? "size-4 animate-spin"
                            : "size-4"
                        }
                        aria-hidden
                      />
                      Refresh
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {forbidden ? (
                  <p className="rounded-md border border-border bg-secondary/30 p-4 text-sm text-muted-foreground">
                    You don&apos;t have permission to read this workspace&apos;s
                    audit log. Ask an admin or owner for access.
                  </p>
                ) : audit.status === "error" ? (
                  <p className="text-sm text-destructive" role="alert">
                    {audit.errorMessage}
                  </p>
                ) : (
                  <>
                    <AuditLogTable
                      loading={audit.status === "loading"}
                      entries={audit.entries}
                    />
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">
                        Page {audit.page + 1}
                      </span>
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={audit.prev}
                          disabled={audit.page === 0 || audit.status === "loading"}
                        >
                          <ChevronLeft className="size-4" aria-hidden />
                          Previous
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={audit.next}
                          disabled={!audit.hasMore || audit.status === "loading"}
                        >
                          Next
                          <ChevronRight className="size-4" aria-hidden />
                        </Button>
                      </div>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </section>
    </main>
  );
}
