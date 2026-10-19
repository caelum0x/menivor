"use client";

import * as React from "react";
import {
  AlertTriangle,
  Check,
  Copy,
  ExternalLink,
  RefreshCw,
  RotateCcw,
  Send,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { RequestOptions } from "@/src/shared/api";
import { getThread, sendReply, setThreadStatus, suggestReplies } from "./api";
import { errorMessageOf, relativeTime, statusLabel } from "./format";
import type { InboxThreadDetail, ReplySuggestions, ThreadStatus } from "./types";

const MAX_REPLY = 1000;

interface ThreadPanelProps {
  threadId: string;
  getOptions: () => Promise<RequestOptions>;
  onChanged: () => void;
}

type Busy = "" | "load" | "suggest" | "send" | "status";

/** One conversation: messages, reply suggestions, send or copy-and-open, status. */
export function ThreadPanel({ threadId, getOptions, onChanged }: ThreadPanelProps) {
  const [thread, setThread] = React.useState<InboxThreadDetail | null>(null);
  const [busy, setBusy] = React.useState<Busy>("load");
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [draft, setDraft] = React.useState("");
  const [suggestions, setSuggestions] = React.useState<ReplySuggestions | null>(null);

  const load = React.useCallback(async () => {
    setBusy("load");
    setError("");
    try {
      setThread(await getThread(threadId, await getOptions()));
    } catch (err) {
      setError(errorMessageOf(err, "Couldn't load this conversation."));
    } finally {
      setBusy("");
    }
  }, [threadId, getOptions]);

  React.useEffect(() => {
    setDraft("");
    setSuggestions(null);
    setNotice("");
    void load();
  }, [load]);

  const run = async (kind: Busy, action: () => Promise<void>) => {
    setBusy(kind);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (err) {
      setError(errorMessageOf(err, "Something went wrong. Try again."));
    } finally {
      setBusy("");
    }
  };

  const onSuggest = () =>
    run("suggest", async () => {
      const result = await suggestReplies(threadId, await getOptions());
      setSuggestions(result);
      if (!draft.trim() && result.suggestions[0]) setDraft(result.suggestions[0]);
    });

  const onSend = () =>
    run("send", async () => {
      const updated = await sendReply(threadId, draft.trim(), await getOptions());
      setThread(updated);
      setDraft("");
      setNotice("Reply posted.");
      onChanged();
    });

  const onStatus = (status: ThreadStatus, replyText = "") =>
    run("status", async () => {
      const updated = await setThreadStatus(threadId, status, replyText, await getOptions());
      setThread(updated);
      if (status === "replied") setDraft("");
      onChanged();
    });

  const onCopyAndOpen = async () => {
    const text = draft.trim();
    if (text) {
      try {
        await navigator.clipboard.writeText(text);
        setNotice("Reply copied. Paste it in the app, then mark it replied here.");
      } catch {
        setNotice("Couldn't copy automatically. Select the text and copy it.");
      }
    }
    if (thread?.reply.open_url) window.open(thread.reply.open_url, "_blank", "noopener,noreferrer");
  };

  if (busy === "load" && !thread) {
    return (
      <Card>
        <CardContent className="space-y-3 p-5">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!thread) {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex items-center justify-between gap-3 p-5">
          <p className="text-sm">{error || "Conversation not found."}</p>
          <Button size="sm" variant="outline" onClick={() => void load()}>
            <RefreshCw className="size-4" aria-hidden /> Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  const manual = thread.reply.mode === "manual";
  const tooLong = draft.length > MAX_REPLY;

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-semibold">{thread.author_name || "Someone"}</p>
            <p className="truncate text-xs text-muted-foreground">
              {thread.kind === "dm"
                ? `${thread.platform_label} direct message`
                : `${thread.platform_label} comment${thread.post_title ? ` on ${thread.post_title}` : ""}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={thread.status === "needs_reply" ? "default" : "secondary"}>
              {statusLabel(thread.status)}
            </Badge>
            {thread.reply.open_url && (
              <Button asChild size="sm" variant="ghost">
                <a href={thread.reply.open_url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="size-4" aria-hidden /> Open
                </a>
              </Button>
            )}
          </div>
        </div>

        <ol className="max-h-80 space-y-2 overflow-y-auto" aria-label="Messages">
          {thread.messages.map((m) => (
            <li
              key={m.id}
              className={cn(
                "rounded-lg px-3 py-2 text-sm",
                m.from_me ? "ml-8 bg-primary/10" : "mr-8 bg-secondary/60",
              )}
            >
              <div className="mb-0.5 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>{m.from_me ? "You" : m.author || "Someone"}</span>
                <span>{relativeTime(m.at)}</span>
              </div>
              <p className="whitespace-pre-wrap break-words">{m.text}</p>
            </li>
          ))}
        </ol>

        {manual && (
          <div className="flex items-start gap-2 rounded-md border border-border bg-secondary/40 p-3 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" aria-hidden />
            <p>
              {thread.reply.reason} You can still write the reply here, copy it, and post it in the
              app.
            </p>
          </div>
        )}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label htmlFor="inbox-reply" className="text-sm font-medium">
              Your reply
            </label>
            <Button size="sm" variant="ghost" onClick={() => void onSuggest()} disabled={busy !== ""}>
              <Sparkles className="size-4" aria-hidden />
              {busy === "suggest" ? "Thinking..." : "Suggest replies"}
            </Button>
          </div>
          {suggestions && suggestions.suggestions.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                {suggestions.source === "ai"
                  ? "Suggestions written by AI. Check them before sending."
                  : "AI suggestions are unavailable right now, so these are starter replies."}
              </p>
              <div className="flex flex-col gap-1">
                {suggestions.suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setDraft(s)}
                    className="rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-secondary/60"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          <Textarea
            id="inbox-reply"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            maxLength={MAX_REPLY + 200}
            placeholder="Write a reply"
          />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className={cn(tooLong && "text-destructive")}>
              {draft.length}/{MAX_REPLY}
            </span>
          </div>
        </div>

        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="text-sm text-muted-foreground" role="status">
            {notice}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          {manual ? (
            <>
              <Button size="sm" onClick={() => void onCopyAndOpen()} disabled={busy !== ""}>
                <Copy className="size-4" aria-hidden /> Copy and open
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void onStatus("replied", draft.trim())}
                disabled={busy !== "" || thread.status === "replied"}
              >
                <Check className="size-4" aria-hidden /> Mark replied
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              onClick={() => void onSend()}
              disabled={busy !== "" || !draft.trim() || tooLong}
            >
              <Send className="size-4" aria-hidden />
              {busy === "send" ? "Sending..." : `Reply on ${thread.platform_label}`}
            </Button>
          )}
          {thread.status !== "done" ? (
            <Button size="sm" variant="ghost" onClick={() => void onStatus("done")} disabled={busy !== ""}>
              <Check className="size-4" aria-hidden /> Mark done
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void onStatus("needs_reply")}
              disabled={busy !== ""}
            >
              <RotateCcw className="size-4" aria-hidden /> Reopen
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
