"use client";

import * as React from "react";
import { Check, Copy, Link2, Loader2, Mail, RefreshCw, X } from "lucide-react";
import type { WorkspaceInvite } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { roleLabel } from "@/components/team/roles";
import type { UseInvitesResult } from "@/components/team/use-invites";
import type { WorkspaceRole } from "@/lib/types";

function formatExpiry(value?: string): string {
  if (!value) return "";
  const t = Date.parse(value);
  if (Number.isNaN(t)) return "";
  return `expires ${new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

function CopyLinkButton({ url }: Readonly<{ url: string }>) {
  const [copied, setCopied] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setFailed(false);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setFailed(true);
    }
  };
  return (
    <Button type="button" size="sm" variant="outline" onClick={() => void copy()}>
      {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
      {copied ? "Link copied" : failed ? "Copy failed, select the link" : "Copy invite link"}
    </Button>
  );
}

/** The one-time accept link just created: copy it or open a pre-filled email. */
function NewLinkPanel({
  invite,
  workspaceName,
  onDismiss,
}: Readonly<{ invite: WorkspaceInvite; workspaceName: string; onDismiss: () => void }>) {
  const subject = `Join ${workspaceName} on Menivor`;
  const body = `You're invited to join the ${workspaceName} workspace on Menivor. Open this link to accept (create a free account with ${invite.email} if you don't have one): ${invite.accept_url}`;
  return (
    <div role="status" className="space-y-3 rounded-md border border-primary/30 bg-primary/5 p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <p>
          Invite ready for <span className="font-medium">{invite.email}</span>
          {invite.notified_in_app ? " (they were also notified in Menivor)" : ""}. Share this
          link with them. It works once and only for that email address.
        </p>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss invite link"
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <input
        readOnly
        value={invite.accept_url}
        aria-label="Invite link"
        onFocus={(e) => e.currentTarget.select()}
        className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs"
      />
      <div className="flex flex-wrap gap-2">
        <CopyLinkButton url={invite.accept_url} />
        <Button asChild size="sm" variant="outline">
          <a
            href={`mailto:${encodeURIComponent(invite.email)}?subject=${encodeURIComponent(
              subject,
            )}&body=${encodeURIComponent(body)}`}
          >
            <Mail className="size-4" aria-hidden /> Email the link
          </a>
        </Button>
      </div>
    </div>
  );
}

export interface PendingInvitesProps {
  workspaceName: string;
  invites: UseInvitesResult;
}

/**
 * Owner/admin view of outstanding invites: the newest accept link (shown once,
 * since the server stores only its hash) plus every pending invite with
 * "new link" and "revoke" actions.
 */
export function PendingInvites({ workspaceName, invites }: Readonly<PendingInvitesProps>) {
  const { status, errorMessage, lastLink, pendingIds, rowErrors } = invites;
  const rows = invites.invites;

  return (
    <div className="space-y-3">
      {lastLink && lastLink.accept_url && (
        <NewLinkPanel
          invite={lastLink}
          workspaceName={workspaceName}
          onDismiss={invites.dismissLastLink}
        />
      )}

      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">Pending invites</h3>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={invites.reload}
          disabled={status === "loading"}
          aria-label="Refresh pending invites"
        >
          <RefreshCw className={status === "loading" ? "size-4 animate-spin" : "size-4"} aria-hidden />
        </Button>
      </div>

      {status === "error" && (
        <p className="text-sm text-destructive" role="alert">
          {errorMessage}
        </p>
      )}
      {status === "ready" && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No pending invites. Invite someone by email above; people without an account get a
          link to join.
        </p>
      )}

      {rows.length > 0 && (
        <ul className="divide-y divide-border rounded-md border border-border">
          {rows.map((row) => {
            const busy = pendingIds.has(row.id);
            return (
              <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{row.email}</p>
                  <p className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                      {roleLabel(row.role as WorkspaceRole)}
                    </Badge>
                    {formatExpiry(row.expires_at)}
                  </p>
                  {rowErrors[row.id] && (
                    <p className="text-xs text-destructive" role="alert">
                      {rowErrors[row.id]}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  {busy && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Working" />}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => void invites.newLink(row)}
                    disabled={busy}
                    title="Create a new link (the previous one stops working)"
                  >
                    <Link2 className="size-4" aria-hidden /> New link
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground hover:text-destructive"
                    onClick={() => void invites.revoke(row)}
                    disabled={busy}
                  >
                    <X className="size-4" aria-hidden /> Revoke
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
