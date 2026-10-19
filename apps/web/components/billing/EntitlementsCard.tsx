"use client";

import * as React from "react";
import { Check, ShieldCheck, X } from "lucide-react";
import type { Entitlements } from "@/lib/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { findPlan } from "./plans";
import { formatEntitlementValue, metricLabel } from "./format";

export interface EntitlementsCardProps {
  entitlements: Entitlements | null;
}

/**
 * The workspace's active-plan entitlement bundle (feature → value) as resolved
 * server-side (`GET /me/workspaces/{id}/entitlements`). Booleans render as an
 * included/excluded row; numbers and strings render their formatted value.
 * Tenant-scoped: only the caller's own workspace bundle is ever shown.
 */
export function EntitlementsCard({
  entitlements,
}: Readonly<EntitlementsCardProps>) {
  const entries = React.useMemo(
    () => Object.entries(entitlements?.entitlements ?? {}),
    [entitlements],
  );
  const plan = findPlan(entitlements?.plan_key);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-5 text-primary" aria-hidden />
          Plan features
        </CardTitle>
        <CardDescription>
          {plan
            ? `Included with your ${plan.name} plan.`
            : "Your active plan's included features."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No entitlements resolved for this workspace.
          </p>
        ) : (
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            {entries.map(([key, value]) => (
              <div
                key={key}
                className="flex items-center justify-between gap-3 border-b border-border/60 pb-2 last:border-b-0"
              >
                <dt className="text-sm text-muted-foreground">
                  {metricLabel(key)}
                </dt>
                <dd className="text-sm font-medium">
                  {typeof value === "boolean" ? (
                    <BooleanValue on={value} />
                  ) : (
                    <span className="tabular-nums">
                      {formatEntitlementValue(value)}
                    </span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function BooleanValue({ on }: Readonly<{ on: boolean }>) {
  return on ? (
    <span className="flex items-center gap-1 text-success">
      <Check className="size-4" aria-hidden /> Yes
    </span>
  ) : (
    <span className="flex items-center gap-1 text-muted-foreground">
      <X className="size-4" aria-hidden /> No
    </span>
  );
}
