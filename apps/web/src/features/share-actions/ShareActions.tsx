"use client";

import { SendToScheduler } from "@/src/features/x-scheduler/SendToScheduler";
import type { SchedulerSource } from "@/src/features/x-scheduler/api";

/**
 * Share-actions slot on a finished render.
 *
 * "Share to X" (the intent-link button) and "Send to Buffer / Typefully" both
 * belong in the same row as Download. This slot only renders the Buffer /
 * Typefully control, marked `data-share-actions`, and does not import the X
 * intent button. Each feature can land in the parent row on its own lines, in
 * either order, and the two controls sit together once both are merged.
 */
export function ShareActions({
  source,
  sourceId,
  kind,
  className,
}: Readonly<{
  source: SchedulerSource;
  sourceId: string;
  kind: "image" | "video";
  className?: string;
}>) {
  if (!sourceId) return null;
  return <SendToScheduler source={source} sourceId={sourceId} kind={kind} className={className} />;
}
