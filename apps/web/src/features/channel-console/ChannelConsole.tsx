"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";

import { readableApiError } from "@/src/shared/launch-gate";
import {
  listChannels,
  listScheduled,
  type Channel,
  type ScheduledPost,
} from "./api";
import { ConnectedChannels } from "./ConnectedChannels";
import { Experiments } from "./Experiments";
import { ScheduleForm } from "./ScheduleForm";
import { ScheduledQueue } from "./ScheduledQueue";

function messageOf(err: unknown, fallback: string): string {
  return readableApiError(err, fallback);
}

/**
 * Channel console — connected accounts, the scheduled-publish queue, a schedule
 * form, and caption/thumbnail A/B experiments. Owns the two read models
 * (channels + queue) and hands a refresh down to the schedule form so a new
 * schedule shows up immediately.
 */
export function ChannelConsole() {
  const { getToken } = useAuth();

  const [channels, setChannels] = React.useState<Channel[]>([]);
  const [channelsLoading, setChannelsLoading] = React.useState(true);
  const [channelsError, setChannelsError] = React.useState("");

  const [scheduled, setScheduled] = React.useState<ScheduledPost[]>([]);
  const [queueLoading, setQueueLoading] = React.useState(true);
  const [queueError, setQueueError] = React.useState("");

  const loadChannels = React.useCallback(async () => {
    setChannelsLoading(true);
    setChannelsError("");
    try {
      const token = (await getToken()) ?? undefined;
      const res = await listChannels({ token });
      setChannels(res ?? []);
    } catch (err) {
      setChannelsError(messageOf(err, "Failed to load channels."));
    } finally {
      setChannelsLoading(false);
    }
  }, [getToken]);

  const loadScheduled = React.useCallback(async () => {
    setQueueLoading(true);
    setQueueError("");
    try {
      const token = (await getToken()) ?? undefined;
      const res = await listScheduled({ token });
      setScheduled(res ?? []);
    } catch (err) {
      setQueueError(messageOf(err, "Failed to load the queue."));
    } finally {
      setQueueLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => {
    void loadChannels();
    void loadScheduled();
  }, [loadChannels, loadScheduled]);

  return (
    <div className="space-y-8">
      <ConnectedChannels
        channels={channels}
        loading={channelsLoading}
        error={channelsError}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <ScheduleForm channels={channels} onScheduled={() => void loadScheduled()} />
        <ScheduledQueue
          scheduled={scheduled}
          loading={queueLoading}
          error={queueError}
        />
      </div>

      <Experiments />
    </div>
  );
}
