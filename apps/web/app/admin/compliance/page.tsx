"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { ErasureRequestsTable } from "@/components/admin/compliance/ErasureRequestsTable";
import { RetentionOverviewTable } from "@/components/admin/compliance/RetentionOverviewTable";
import { OperatorErasureCard } from "@/components/admin/compliance/OperatorErasureCard";
import { useAdminCompliance } from "@/lib/use-admin-compliance";

/**
 * Platform-admin compliance console (/admin/compliance, `is_staff` only — the
 * surrounding {@link AdminShell} gates access and every underlying endpoint
 * re-enforces `is_staff` server-side). A cross-tenant view of right-to-erasure
 * requests and workspace retention posture, plus an operator-initiated erasure
 * action. This surface is SEPARATE from per-workspace RBAC — a workspace owner
 * is not a platform admin.
 */
export default function AdminCompliancePage() {
  const { status, requests, policies, errorMessage, eraseUser } =
    useAdminCompliance();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Compliance</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Right-to-erasure requests and data-retention posture across all
          tenants.
        </p>
      </div>

      {status === "loading" && (
        <div className="flex items-center justify-center gap-2 py-16 text-muted-foreground">
          <Loader2 className="size-5 animate-spin" aria-hidden />
          Loading compliance overview…
        </div>
      )}

      {status === "error" && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive"
        >
          {errorMessage}
        </div>
      )}

      {status === "ready" && (
        <>
          <section className="space-y-3">
            <h2 className="text-lg font-semibold tracking-tight">
              Erasure requests
            </h2>
            <ErasureRequestsTable requests={requests} />
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-semibold tracking-tight">
              Retention overview
            </h2>
            <RetentionOverviewTable policies={policies} />
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-semibold tracking-tight text-destructive">
              Operator actions
            </h2>
            <OperatorErasureCard onErase={eraseUser} />
          </section>
        </>
      )}
    </div>
  );
}
