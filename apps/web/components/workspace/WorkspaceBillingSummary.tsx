"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, ArrowUpRight, CreditCard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EntitlementsCard } from "@/components/billing/EntitlementsCard";
import { UsageMeters } from "@/components/billing/UsageMeters";
import { useWorkspaceBilling } from "@/lib/use-workspace-billing";
import { useWorkspacePermissions } from "@/lib/use-workspace-permissions";

export interface WorkspaceBillingSummaryProps {
  /** The selected workspace, or `null` while none is chosen. */
  workspaceId: string | null;
}

/**
 * A read-only plan + usage snapshot for the selected workspace, shown beneath
 * the members pane on the Workspaces surface. Entitlements and usage are
 * membership reads (any member sees them); the "Manage billing" link only
 * appears for callers who hold `billing.manage`. Tenant-scoped — every read is
 * keyed to `workspaceId`, so no other workspace's numbers ever appear.
 */
export function WorkspaceBillingSummary({
  workspaceId,
}: Readonly<WorkspaceBillingSummaryProps>) {
  const perms = useWorkspacePermissions(workspaceId);
  const canManage = perms.has("billing.manage");
  const { status, entitlements, usage, errorMessage, period } =
    useWorkspaceBilling(workspaceId, canManage);

  if (!workspaceId) return null;

  return (
    <section aria-labelledby="workspace-billing" className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <h2
          id="workspace-billing"
          className="flex items-center gap-2 text-lg font-semibold tracking-tight"
        >
          <CreditCard className="size-5 text-primary" aria-hidden />
          Plan &amp; usage
        </h2>
        {canManage && (
          <Button asChild variant="outline" size="sm">
            <Link href="/settings/billing">
              Manage billing
              <ArrowUpRight className="size-4" aria-hidden />
            </Link>
          </Button>
        )}
      </div>

      {(status === "loading" || status === "idle") && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-56 w-full rounded-lg" />
          <Skeleton className="h-56 w-full rounded-lg" />
        </div>
      )}

      {status === "error" && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-start gap-3 p-6">
            <AlertTriangle
              className="mt-0.5 size-5 shrink-0 text-destructive"
              aria-hidden
            />
            <div>
              <p className="font-medium">Couldn&apos;t load billing details</p>
              <p className="text-sm text-muted-foreground">{errorMessage}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {status === "ready" && (
        <>
          {errorMessage && (
            <p className="text-sm text-muted-foreground" role="status">
              Some billing details couldn&apos;t be loaded: {errorMessage}
            </p>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <EntitlementsCard entitlements={entitlements} />
            <UsageMeters usage={usage} period={period} />
          </div>
        </>
      )}
    </section>
  );
}
