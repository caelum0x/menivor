import { Badge } from "@/components/ui/badge";
import type { ErasureStatus } from "@/lib/types";

/** Map an erasure lifecycle status to a badge variant + label. */
export function ErasureStatusBadge({ status }: { status: ErasureStatus }) {
  if (status === "completed") return <Badge variant="success">Completed</Badge>;
  if (status === "processing")
    return <Badge variant="secondary">Processing</Badge>;
  if (status === "requested")
    return <Badge variant="outline">Requested</Badge>;
  return <Badge variant="secondary">{status || "—"}</Badge>;
}
