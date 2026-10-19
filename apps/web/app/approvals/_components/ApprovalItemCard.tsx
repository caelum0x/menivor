"use client";

import * as React from "react";
import Link from "next/link";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ErrorText, useRequestOptions } from "@/src/features/ad-studio/shared";
import { LaunchGateNotice, readableApiError, type FeatureGate } from "@/src/shared/launch-gate";
import { ApprovalResult } from "./ApprovalResult";
import { SOURCE_LABELS, decideApproval, type ApprovalItem } from "./api";
import { safeServerText } from "@/src/shared/errors/friendly";

const RISK_VARIANT: Record<ApprovalItem["risk"], BadgeVariant> = {
  low: "secondary",
  medium: "outline",
  high: "destructive",
};

const STATUS_VARIANT: Partial<Record<ApprovalItem["status"], BadgeVariant>> = {
  executed: "success",
  approved: "success",
  edited: "success",
  rejected: "secondary",
  expired: "secondary",
  failed: "destructive",
};

function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

/** Sources whose approval schedules real posts, so they follow the publishing launch gate. */
export const PUBLISHING_SOURCES: ReadonlySet<ApprovalItem["source"]> = new Set(["publish_hold", "design_publish"]);

const OPEN_GATE: FeatureGate = { open: true, reason: "" };

/** One pending (or decided) item with approve / edit / reject controls. */
export function ApprovalItemCard({
  item,
  onDecided,
  publishGate = OPEN_GATE,
  gateLoading = false,
}: {
  item: ApprovalItem;
  onDecided: (next: ApprovalItem) => void;
  /** Publishing launch gate; approving a post-scheduling item waits while it is closed. */
  publishGate?: FeatureGate;
  gateLoading?: boolean;
}) {
  const requestOptions = useRequestOptions();
  const editable = item.payload.editable_fields ?? [];
  const canEditText = item.can_decide && editable.includes("text");
  const originalText = typeof item.payload.text === "string" ? item.payload.text : "";
  const [text, setText] = React.useState(originalText);
  const [editing, setEditing] = React.useState(false);
  const [busy, setBusy] = React.useState<"" | "approve" | "reject">("");
  const [error, setError] = React.useState("");
  const postsSomething = PUBLISHING_SOURCES.has(item.source);
  const approveBlocked = postsSomething && (gateLoading || !publishGate.open);

  const decide = async (decision: "approve" | "reject") => {
    setBusy(decision);
    setError("");
    try {
      const edits = decision === "approve" && canEditText && text.trim() !== originalText.trim() ? { text } : undefined;
      const outcome = await decideApproval(item.id, decision, { edits }, await requestOptions());
      setEditing(false);
      onDecided(outcome.item);
    } catch (err) {
      setError(readableApiError(err, "Couldn't record your decision. Try again."));
    } finally {
      setBusy("");
    }
  };

  const openPath = typeof item.payload.open_path === "string" && item.payload.open_path.startsWith("/")
    ? item.payload.open_path
    : null;

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{SOURCE_LABELS[item.source] ?? item.source}</Badge>
          <Badge variant={RISK_VARIANT[item.risk] ?? "outline"}>{item.risk} risk</Badge>
          {item.status !== "pending" ? (
            <Badge variant={STATUS_VARIANT[item.status] ?? "outline"}>{item.status}</Badge>
          ) : null}
          <span className="ml-auto text-xs text-muted-foreground">{formatWhen(item.created_at)}</span>
        </div>
        <div>
          <h3 className="font-medium">{item.title || "Untitled item"}</h3>
          {item.summary ? <p className="mt-1 whitespace-pre-line text-sm text-muted-foreground">{item.summary}</p> : null}
        </div>

        {editing ? (
          <div className="space-y-1">
            <label htmlFor={`approval-text-${item.id}`} className="text-xs font-medium">
              Text to send
            </label>
            <Textarea
              id={`approval-text-${item.id}`}
              value={text}
              maxLength={2000}
              rows={4}
              onChange={(event) => setText(event.target.value)}
            />
          </div>
        ) : null}

        {item.error ? <p className="text-sm text-destructive">{safeServerText(item.error, "This item hit a problem. Please try again.")}</p> : null}
        {item.result && Object.keys(item.result).length ? <ApprovalResult result={item.result} /> : null}
        {item.decided_at ? (
          <p className="text-xs text-muted-foreground">
            Decided {formatWhen(item.decided_at)}
            {item.decided_via ? ` via ${item.decided_via}` : ""}
            {item.decision_note ? `: ${item.decision_note}` : ""}
          </p>
        ) : null}
        {error ? <ErrorText message={error} /> : null}
        {item.can_decide && postsSomething ? (
          <LaunchGateNotice
            gate={publishGate}
            meanwhile="You can reject it now, or leave it here and approve it once publishing opens."
          />
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          {item.can_decide ? (
            <>
              <Button size="sm" onClick={() => decide("approve")} disabled={busy !== "" || approveBlocked}>
                {busy === "approve" ? "Approving..." : editing ? "Approve with edits" : "Approve"}
              </Button>
              {canEditText && !editing ? (
                <Button size="sm" variant="outline" onClick={() => setEditing(true)} disabled={busy !== ""}>
                  Edit
                </Button>
              ) : null}
              <Button size="sm" variant="ghost" onClick={() => decide("reject")} disabled={busy !== ""}>
                {busy === "reject" ? "Rejecting..." : "Reject"}
              </Button>
            </>
          ) : null}
          {openPath && openPath !== "/approvals" ? (
            <Link href={openPath} className="ml-auto text-sm underline underline-offset-4">
              Open source
            </Link>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
