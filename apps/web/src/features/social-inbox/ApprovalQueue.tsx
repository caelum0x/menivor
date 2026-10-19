"use client";

import * as React from "react";
import { Check, ExternalLink, Loader2, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import type { RequestOptions } from "@/src/shared/api";
import {
  approveDraft,
  cleanError,
  listApprovals,
  openUrlOf,
  rejectDraft,
  type EngagementAction,
} from "./autopilot-api";
import { relativeTime } from "./format";
import { safeServerText } from "@/src/shared/errors/friendly";

const MAX_REPLY = 1000;

interface ApprovalQueueProps {
  getOptions: () => Promise<RequestOptions>;
  onChanged: () => void;
  onOpenThread: (threadId: string) => void;
}

interface RowState {
  text: string;
  busy: boolean;
  error: string;
  openUrl: string;
}

/** Reply drafts the autopilot wrote, waiting for the creator: edit, send or discard. */
export function ApprovalQueue({ getOptions, onChanged, onOpenThread }: Readonly<ApprovalQueueProps>) {
  const [items, setItems] = React.useState<readonly EngagementAction[] | null>(null);
  const [total, setTotal] = React.useState(0);
  const [rows, setRows] = React.useState<Readonly<Record<string, RowState>>>({});
  const [loadError, setLoadError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const page = await listApprovals(0, await getOptions());
      setItems(page.actions);
      setTotal(page.total);
      setRows(Object.fromEntries(page.actions.map((a) => [a.id, { text: a.text, busy: false, error: "", openUrl: "" }])));
      setLoadError("");
    } catch (err) {
      setLoadError(cleanError(err, "Couldn't load drafts."));
    }
  }, [getOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const patch = (id: string, next: Partial<RowState>) =>
    setRows((prev) => ({ ...prev, [id]: { ...(prev[id] ?? { text: "", busy: false, error: "", openUrl: "" }), ...next } }));

  const remove = (id: string) => {
    setItems((prev) => (prev ?? []).filter((a) => a.id !== id));
    setTotal((t) => Math.max(0, t - 1));
  };

  const send = async (action: EngagementAction) => {
    const row = rows[action.id];
    patch(action.id, { busy: true, error: "", openUrl: "" });
    try {
      await approveDraft(action.id, row?.text ?? action.text, await getOptions());
      remove(action.id);
      onChanged();
    } catch (err) {
      patch(action.id, { busy: false, error: cleanError(err, "Couldn't send this reply."), openUrl: openUrlOf(err) });
    }
  };

  const discard = async (action: EngagementAction) => {
    patch(action.id, { busy: true, error: "" });
    try {
      await rejectDraft(action.id, await getOptions());
      remove(action.id);
      onChanged();
    } catch (err) {
      patch(action.id, { busy: false, error: cleanError(err, "Couldn't discard this draft.") });
    }
  };

  if (loadError) return <p className="text-sm text-destructive">{loadError}</p>;
  if (items === null) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-muted-foreground">
          No drafts waiting. When the autopilot drafts a reply to a positive comment, it shows up here for you
          to send or discard.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {total > items.length && (
        <p className="text-xs text-muted-foreground">
          Showing {items.length} of {total} drafts.
        </p>
      )}
      {items.map((action) => {
        const row = rows[action.id] ?? { text: action.text, busy: false, error: "", openUrl: "" };
        return (
          <Card key={action.id}>
            <CardContent className="space-y-3 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="font-medium">
                  {action.author_name || "Someone"} on {action.platform_label}
                </span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline">{action.label.replace("_", " ")}</Badge>
                  {relativeTime(action.created_at)}
                </span>
              </div>
              <blockquote className="border-l-2 border-border pl-3 text-sm text-muted-foreground">
                {action.excerpt}
              </blockquote>
              <div className="space-y-1">
                <Textarea
                  rows={2}
                  maxLength={MAX_REPLY}
                  value={row.text}
                  disabled={row.busy}
                  aria-label="Reply draft"
                  onChange={(e) => patch(action.id, { text: e.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                  {action.text_source === "ai" ? "Drafted by AI" : "Drafted from a template"}. Edit before sending if
                  you like.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={row.busy || !row.text.trim()} onClick={() => void send(action)}>
                  {row.busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Check className="size-4" aria-hidden />}
                  Send reply
                </Button>
                <Button size="sm" variant="ghost" disabled={row.busy} onClick={() => void discard(action)}>
                  <Trash2 className="size-4" aria-hidden /> Discard
                </Button>
                {action.thread_id && (
                  <Button size="sm" variant="outline" onClick={() => onOpenThread(action.thread_id as string)}>
                    Open conversation
                  </Button>
                )}
              </div>
              {row.error && (
                <p className="text-xs text-destructive" role="alert">
                  {safeServerText(row.error, "This reply could not be sent.")}{" "}
                  {row.openUrl && (
                    <a href={row.openUrl} target="_blank" rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline">
                      Reply in the app <ExternalLink className="size-3" aria-hidden />
                    </a>
                  )}
                </p>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
