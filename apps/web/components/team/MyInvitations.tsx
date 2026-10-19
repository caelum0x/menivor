"use client";

import * as React from "react";
import { Loader2, MailOpen } from "lucide-react";
import { ApiError, acceptMyInvite, listMyInvites, type WorkspaceInvite } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { roleLabel } from "@/components/team/roles";
import { useApiToken } from "@/lib/use-api-token";
import type { WorkspaceRole } from "@/lib/types";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface MyInvitationsProps {
  /** Called with the joined workspace id after a successful accept. */
  onAccepted: (workspaceId: string | undefined) => void;
}

function messageFor(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/**
 * Pending workspace invitations addressed to the signed-in user's email
 * (GET /me/invites), each with a one-click Join. Renders nothing when there
 * are none, so it can sit at the top of the workspace page unconditionally.
 */
export function MyInvitations({ onAccepted }: Readonly<MyInvitationsProps>) {
  const getApiToken = useApiToken();
  const [invites, setInvites] = React.useState<readonly WorkspaceInvite[]>([]);
  const [pendingId, setPendingId] = React.useState<string | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const token = await getApiToken();
        const rows = await listMyInvites({ token });
        if (!cancelled) setInvites(rows);
      } catch {
        // Guests and signed-out visitors have no inbox; nothing to show.
        if (!cancelled) setInvites([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getApiToken]);

  const accept = async (invite: WorkspaceInvite) => {
    setPendingId(invite.id);
    setError("");
    try {
      const token = await getApiToken();
      const result = await acceptMyInvite(invite.id, { token });
      setInvites((prev) => prev.filter((i) => i.id !== invite.id));
      onAccepted(result.workspace_id ?? invite.workspace_id);
    } catch (err) {
      setError(messageFor(err, "Couldn't join this workspace."));
    } finally {
      setPendingId(null);
    }
  };

  if (invites.length === 0) return null;

  return (
    <Card className="mb-6 border-primary/40 bg-primary/5">
      <CardContent className="space-y-3 py-4">
        <p className="flex items-center gap-2 font-medium">
          <MailOpen className="size-4 text-primary" aria-hidden />
          You have {invites.length} workspace invitation{invites.length === 1 ? "" : "s"}
        </p>
        <ul className="space-y-2">
          {invites.map((invite) => (
            <li key={invite.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>
                <span className="font-medium">{invite.workspace_name || "A workspace"}</span>{" "}
                <span className="text-muted-foreground">
                  as {roleLabel(invite.role as WorkspaceRole)}
                </span>
              </span>
              <Button size="sm" onClick={() => void accept(invite)} disabled={pendingId !== null}>
                {pendingId === invite.id && <Loader2 className="size-4 animate-spin" aria-hidden />}
                Join
              </Button>
            </li>
          ))}
        </ul>
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
