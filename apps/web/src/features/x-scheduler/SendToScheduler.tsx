"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import { CalendarClock, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  X_CAPTION_MAX,
  captionTooLong,
  listSchedulerConnections,
  listSchedulerTargets,
  providerLabel,
  scheduleSchedulerPost,
  type ScheduleWhen,
  type SchedulerConnection,
  type SchedulerProvider,
  type SchedulerSource,
  type SchedulerTarget,
} from "./api";

const WHEN_OPTIONS: ReadonlyArray<{ value: ScheduleWhen; label: string }> = [
  { value: "now", label: "Post now" },
  { value: "queue", label: "Add to queue" },
  { value: "schedule", label: "Pick a time" },
];

/**
 * Send one finished image or video to the caller's Buffer or Typefully account.
 * Sits beside the render's download / share actions. Menivor does not call the X API.
 */
export function SendToScheduler({
  source,
  sourceId,
  kind,
  className,
}: Readonly<{
  source: SchedulerSource;
  sourceId: string;
  kind: "image" | "video";
  /** Extra classes for the parent row (for example `col-span-2` in a grid). */
  className?: string;
}>) {
  const { getToken } = useAuth();
  const getTokenRef = React.useRef(getToken);
  getTokenRef.current = getToken;
  const [open, setOpen] = React.useState(false);
  const [connections, setConnections] = React.useState<SchedulerConnection[] | null>(null);
  const [provider, setProvider] = React.useState<SchedulerProvider>("buffer");
  const [targets, setTargets] = React.useState<SchedulerTarget[]>([]);
  const [targetId, setTargetId] = React.useState("");
  const [caption, setCaption] = React.useState("");
  const [when, setWhen] = React.useState<ScheduleWhen>("queue");
  const [whenLocal, setWhenLocal] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [sending, setSending] = React.useState(false);
  const [error, setError] = React.useState("");
  const [done, setDone] = React.useState("");

  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    void (async () => {
      try {
        const rows = await listSchedulerConnections({ token: (await getTokenRef.current()) ?? "" });
        if (cancelled) return;
        setConnections(rows);
        const first = rows.find((row) => row.connected);
        if (first) setProvider(first.provider);
      } catch (err) {
        if (!cancelled) setError(friendlyErrorMessage(err, "Could not load Buffer and Typefully."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const connected = (connections ?? []).filter((row) => row.connected);
  const connectedKey = connected.map((row) => row.provider).join(",");

  React.useEffect(() => {
    if (!open || !connectedKey.split(",").filter(Boolean).includes(provider)) return;
    let cancelled = false;
    setTargets([]);
    setTargetId("");
    void (async () => {
      try {
        const rows = await listSchedulerTargets(provider, { token: (await getTokenRef.current()) ?? "" });
        if (cancelled) return;
        setTargets(rows);
        setTargetId(rows[0]?.id ?? "");
      } catch (err) {
        if (!cancelled) setError(friendlyErrorMessage(err, "Could not load X accounts."));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, provider, connectedKey]);

  const send = async () => {
    setError("");
    setDone("");
    if (captionTooLong(caption)) {
      setError("X posts are limited to 280 characters.");
      return;
    }
    if (!targetId) {
      setError("Choose an X account.");
      return;
    }
    let scheduled_at: string | undefined;
    if (when === "schedule") {
      const parsed = new Date(whenLocal);
      if (!whenLocal || Number.isNaN(parsed.getTime()) || parsed.getTime() <= Date.now()) {
        setError("Pick a time in the future.");
        return;
      }
      scheduled_at = parsed.toISOString();
    }
    setSending(true);
    try {
      const result = await scheduleSchedulerPost(
        { provider, target_id: targetId, source, source_id: sourceId, caption, when, scheduled_at },
        { token: (await getTokenRef.current()) ?? "" },
      );
      setDone(result.message);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not send that post."));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className={cn(open && "w-full basis-full", className)} data-share-actions="">
      <Button type="button" size="sm" variant="outline" onClick={() => setOpen((value) => !value)}>
        <CalendarClock className="mr-1 h-4 w-4" aria-hidden />
        Send to Buffer / Typefully
      </Button>
      {open ? (
        <form
          className="mt-2 space-y-3 rounded-md border border-border bg-secondary/20 p-3"
          aria-label={`Send this ${kind} to Buffer or Typefully`}
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <p className="text-xs text-muted-foreground">
            Posts through your Buffer or Typefully account. Menivor does not call the X API.
          </p>
          {loading ? <p className="text-sm text-muted-foreground">Loading accounts…</p> : null}
          {connections && connected.length === 0 ? (
            <p className="text-sm">
              Connect a key in{" "}
              <Link href="/settings/scheduler" className="underline underline-offset-2">
                settings
              </Link>
              .
            </p>
          ) : null}
          {connected.length > 0 ? (
            <>
              <div className="flex flex-wrap gap-2">
                {connected.map((row) => (
                  <Button
                    key={row.provider}
                    type="button"
                    size="sm"
                    variant={provider === row.provider ? "secondary" : "ghost"}
                    onClick={() => setProvider(row.provider)}
                  >
                    {providerLabel(row.provider)}
                  </Button>
                ))}
              </div>
              <div className="space-y-1">
                <Label htmlFor={`scheduler-target-${sourceId}`}>X account</Label>
                <select
                  id={`scheduler-target-${sourceId}`}
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                  value={targetId}
                  onChange={(event) => setTargetId(event.target.value)}
                >
                  {targets.length === 0 ? <option value="">No X account on this connection</option> : null}
                  {targets.map((target) => (
                    <option key={target.id} value={target.id}>
                      {target.handle || target.name}
                      {target.organization ? ` · ${target.organization}` : ""}
                      {target.publishing_quota?.remaining != null
                        ? ` · ${target.publishing_quota.remaining} publishes left`
                        : ""}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <Label htmlFor={`scheduler-caption-${sourceId}`}>Caption</Label>
                  <span className={captionTooLong(caption) ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
                    {`${caption.length}/${X_CAPTION_MAX}`}
                  </span>
                </div>
                <Textarea
                  id={`scheduler-caption-${sourceId}`}
                  value={caption}
                  maxLength={X_CAPTION_MAX + 20}
                  rows={3}
                  onChange={(event) => setCaption(event.target.value)}
                  placeholder="What should the post say?"
                />
              </div>
              <fieldset className="space-y-1">
                <legend className="text-sm font-medium">When</legend>
                <div className="flex flex-wrap gap-2">
                  {WHEN_OPTIONS.map((option) => (
                    <label key={option.value} className="flex items-center gap-1 text-sm">
                      <input
                        type="radio"
                        name={`scheduler-when-${sourceId}`}
                        value={option.value}
                        checked={when === option.value}
                        onChange={() => setWhen(option.value)}
                      />
                      {option.label}
                    </label>
                  ))}
                </div>
              </fieldset>
              {when === "schedule" ? (
                <input
                  type="datetime-local"
                  aria-label="Publish at"
                  className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                  value={whenLocal}
                  onChange={(event) => setWhenLocal(event.target.value)}
                />
              ) : null}
              <Button type="submit" size="sm" disabled={sending || captionTooLong(caption)}>
                {sending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
                Send
              </Button>
            </>
          ) : null}
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          {done ? <p className="text-sm">{done}</p> : null}
        </form>
      ) : null}
    </div>
  );
}
