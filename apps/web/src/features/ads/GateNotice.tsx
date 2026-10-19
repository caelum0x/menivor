import { Lock } from "lucide-react";

import type { AdsGate } from "./api";
import { NOT_ENABLED_REASON } from "./api";

/** Explains why paid ads are unavailable (platform app review pending). */
export function GateNotice({ gate }: { gate: AdsGate | null }) {
  if (gate && gate.enabled) return null;
  return (
    <div role="status" className="flex gap-3 rounded-lg border border-border bg-secondary/40 p-4 text-sm">
      <Lock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="space-y-1">
        <p className="font-medium">{gate?.reason || NOT_ENABLED_REASON}</p>
        <p className="text-muted-foreground">
          Launching paid campaigns needs Menivor&apos;s Meta and TikTok business apps to pass platform app review.
          Until then you can still render ads in Ad Studio, download them, and run them from your own Ads Manager.
        </p>
      </div>
    </div>
  );
}

/** One-line note for a single platform that is not enabled yet. */
export function PlatformDisabled({ reason }: { reason: string }) {
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Lock className="h-4 w-4" aria-hidden />
      {reason || NOT_ENABLED_REASON}
    </p>
  );
}
