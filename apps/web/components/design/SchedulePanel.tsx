"use client";

import * as React from "react";
import Link from "next/link";
import { CalendarClock, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { getChannels, type Channel } from "@/components/calendar/board-api";

import { scheduleDesign } from "./api";
import { ErrorText, errorMessage } from "./shared";
import { LaunchGateNotice, useLaunchGate } from "@/src/shared/launch-gate";
import { PLATFORM_OPTIONS, type DesignDoc } from "./types";

function localInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export interface SchedulePanelProps {
  design: DesignDoc;
  getOptions: () => Promise<{ token?: string }>;
  onScheduled: (design: DesignDoc) => void;
  onClose: () => void;
}

/** Hand the exported images to the approvals queue with where and when to post them. */
export function SchedulePanel({ design, getOptions, onScheduled, onClose }: SchedulePanelProps) {
  const publishGate = useLaunchGate().gate.publishing;
  const [platforms, setPlatforms] = React.useState<string[]>(["instagram"]);
  const [caption, setCaption] = React.useState(design.prompt.slice(0, 2200));
  const [when, setWhen] = React.useState(() => localInputValue(new Date(Date.now() + 60 * 60 * 1000)));
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [done, setDone] = React.useState(false);
  // Telegram / Discord / Mastodon channels the caller can post to, grouped by kind.
  const [channels, setChannels] = React.useState<Channel[]>([]);
  const [channelIds, setChannelIds] = React.useState<string[]>([]);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const data = await getChannels(await getOptions());
        if (alive) setChannels(data.channels.filter((c) => c.can_post));
      } catch {
        // Channels are optional here; the approval result explains any missing connection.
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const channelsFor = (kind: string) => channels.filter((c) => c.kind === kind);
  const toggleChannel = (id: string) =>
    setChannelIds((list) => (list.includes(id) ? list.filter((c) => c !== id) : [...list, id]));

  const toggle = (id: string) =>
    setPlatforms((list) => (list.includes(id) ? list.filter((p) => p !== id) : [...list, id]));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (platforms.length === 0) {
      setError("Choose at least one place to post.");
      return;
    }
    // A kind with several channels needs an explicit pick; one channel is used as-is.
    const unpicked = platforms.find((p) => {
      const options = channelsFor(p);
      return options.length > 1 && !options.some((c) => channelIds.includes(c.id));
    });
    if (unpicked) {
      const label = PLATFORM_OPTIONS.find((o) => o.id === unpicked)?.label ?? unpicked;
      setError(`You have several ${label} channels; choose which ones to post to.`);
      return;
    }
    const chosenChannels = channelIds.filter((id) => {
      const channel = channels.find((c) => c.id === id);
      return channel ? platforms.includes(channel.kind) : false;
    });
    const at = new Date(when);
    if (Number.isNaN(at.getTime())) {
      setError("Pick a valid date and time.");
      return;
    }
    setBusy(true);
    try {
      const res = await scheduleDesign(design.id, { platforms, caption, scheduled_at: at.toISOString(), channel_ids: chosenChannels }, await getOptions());
      onScheduled(res.design);
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <Card>
        <CardContent className="space-y-3 p-4 text-sm">
          <p className="font-medium">Queued for approval.</p>
          <p className="text-muted-foreground">
            The design is in your approvals queue with the places and time you picked. Approve it there or from
            Rally: approving queues one image post per connected place at that time. Places that are not connected
            or cannot take images (TikTok, YouTube, store listings, websites) are listed with the reason.
          </p>
          <div className="flex gap-2">
            <Button asChild size="sm">
              <Link href="/approvals">Open approvals</Link>
            </Button>
            <Button size="sm" variant="ghost" onClick={onClose}>
              Close
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="p-4">
        <form className="space-y-3" onSubmit={submit}>
          <p className="flex items-center gap-2 font-medium">
            <CalendarClock className="size-4" aria-hidden /> Schedule this design
          </p>
          <fieldset className="space-y-1">
            <legend className="text-xs text-muted-foreground">Where</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {PLATFORM_OPTIONS.map((p) => (
                <label key={p.id} className="flex items-center gap-1.5 text-sm">
                  <input type="checkbox" checked={platforms.includes(p.id)} onChange={() => toggle(p.id)} />
                  {p.label}
                </label>
              ))}
            </div>
          </fieldset>
          {platforms
            .filter((p) => channelsFor(p).length > 1)
            .map((kind) => (
              <fieldset key={kind} className="space-y-1">
                <legend className="text-xs text-muted-foreground">
                  Which {PLATFORM_OPTIONS.find((o) => o.id === kind)?.label ?? kind} channels
                </legend>
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  {channelsFor(kind).map((c) => (
                    <label key={c.id} className="flex items-center gap-1.5 text-sm">
                      <input type="checkbox" checked={channelIds.includes(c.id)} onChange={() => toggleChannel(c.id)} />
                      {c.label}
                      {c.shared ? <span className="text-xs text-muted-foreground">(team)</span> : null}
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          <div className="space-y-1">
            <Label htmlFor="schedule-caption" className="text-xs text-muted-foreground">
              Caption
            </Label>
            <Textarea id="schedule-caption" rows={3} maxLength={2200} value={caption} onChange={(e) => setCaption(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="schedule-when" className="text-xs text-muted-foreground">
              When (your time zone)
            </Label>
            <Input id="schedule-when" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
          </div>
          <LaunchGateNotice
            gate={publishGate}
            meanwhile="You can still add it to approvals now. Approving it, which schedules the posts, waits until publishing opens."
          />
          <ErrorText message={error} />
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={busy}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Add to approvals
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
