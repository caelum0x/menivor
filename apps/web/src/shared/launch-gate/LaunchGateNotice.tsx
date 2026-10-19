import * as React from "react";
import { Lock } from "lucide-react";

import type { FeatureGate } from "./gate";

export interface LaunchGateNoticeProps {
  gate: FeatureGate;
  /** Optional line on what the person can still do meanwhile. */
  meanwhile?: React.ReactNode;
  className?: string;
}

/** Up-front explanation for a publish/schedule/checkout control that is closed. */
export function LaunchGateNotice({ gate, meanwhile, className }: Readonly<LaunchGateNoticeProps>) {
  if (gate.open || !gate.reason) return null;
  return (
    <div
      role="status"
      className={`flex items-start gap-3 rounded-md border border-border bg-muted/40 p-3 text-sm ${className ?? ""}`}
    >
      <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="space-y-1">
        <p>{gate.reason}</p>
        {meanwhile ? <p className="text-muted-foreground">{meanwhile}</p> : null}
      </div>
    </div>
  );
}
