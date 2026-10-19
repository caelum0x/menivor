"use client";

import * as React from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import type { WorkflowRun } from "./api";
import { runStatusLabel, stepStatusLabel } from "./graph";

export function RunPanel({ run }: { run: WorkflowRun }) {
  const waiting = run.steps.some((s) => s.status === "pending_approval");
  return (
    <div className="space-y-2" data-testid="run-panel">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold">Last run</h3>
        <Badge variant="secondary">{runStatusLabel(run.status)}</Badge>
      </div>
      <ol className="space-y-1">
        {run.steps.map((s) => (
          <li key={s.node_id} className="flex items-center justify-between gap-2 text-sm">
            <span>{s.label}</span>
            <span className="text-xs text-muted-foreground">
              {stepStatusLabel(s.status)}
              {s.credits ? ` (${s.credits} credits)` : ""}
            </span>
          </li>
        ))}
      </ol>
      {run.error ? <p className="text-sm text-destructive">{run.error}</p> : null}
      {waiting ? (
        <Link href="/agent" className="text-sm text-primary underline-offset-2 hover:underline">
          Approve in the Agent queue
        </Link>
      ) : null}
    </div>
  );
}
