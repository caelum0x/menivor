import { CheckCircle2, TriangleAlert } from "lucide-react";
import type { Connection } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { isConnectionExpired } from "@/components/connections/format";

export interface ConnectionStatusBadgeProps {
  connection: Connection;
}

/**
 * Compact status pill for a connected account: `success` while the stored token
 * is valid, `destructive` when it needs a reconnect (backend-flagged `expired` or
 * a past `token_expires_at`).
 */
export function ConnectionStatusBadge({
  connection,
}: Readonly<ConnectionStatusBadgeProps>) {
  const expired = isConnectionExpired(connection);
  if (expired) {
    return (
      <Badge variant="destructive">
        <TriangleAlert className="size-3.5" aria-hidden />
        Expired
      </Badge>
    );
  }
  return (
    <Badge variant="success">
      <CheckCircle2 className="size-3.5" aria-hidden />
      Connected
    </Badge>
  );
}
