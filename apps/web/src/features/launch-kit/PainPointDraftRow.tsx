"use client";

import * as React from "react";
import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { PainPointDraft } from "./api";
import { draftStatusLabel, threadMeta } from "./view-model";

interface Props {
  readonly draft: PainPointDraft;
  readonly onApprove: (id: string) => Promise<void>;
  readonly onDismiss: (id: string) => Promise<void>;
}

/**
 * One saved pain-point thread + its drafted reply. There is deliberately no
 * "post" button here — see the api module's docstring: posting is always a
 * human, on Reddit, by hand.
 */
export function PainPointDraftRow({ draft, onApprove, onDismiss }: Props) {
  const [busy, setBusy] = React.useState<"approve" | "dismiss" | "">("");

  const run = async (action: "approve" | "dismiss", fn: () => Promise<void>) => {
    setBusy(action);
    try {
      await fn();
    } finally {
      setBusy("");
    }
  };

  return (
    <li className="space-y-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <a
            href={draft.thread_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-medium hover:underline"
          >
            {draft.thread_title || draft.thread_url} <ExternalLink className="size-3" aria-hidden />
          </a>
          <p className="text-sm text-muted-foreground">
            r/{draft.subreddit || "all"} · {threadMeta(draft.upvotes, draft.age_days)}
          </p>
        </div>
        <Badge variant={draft.status === "approved" ? "success" : draft.status === "dismissed" ? "outline" : "secondary"}>
          {draftStatusLabel(draft.status)}
        </Badge>
      </div>
      <p className="rounded-md border border-white/10 bg-white/[0.03] p-3 text-sm">{draft.draft_reply}</p>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={busy !== "" || draft.status === "approved"}
          onClick={() => void run("approve", () => onApprove(draft.id))}
        >
          {busy === "approve" ? "Saving..." : "Approve"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={busy !== "" || draft.status === "dismissed"}
          onClick={() => void run("dismiss", () => onDismiss(draft.id))}
        >
          {busy === "dismiss" ? "Saving..." : "Dismiss"}
        </Button>
      </div>
    </li>
  );
}
