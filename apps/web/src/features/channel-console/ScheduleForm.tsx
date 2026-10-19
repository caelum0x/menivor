"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { CalendarClock, Loader2 } from "lucide-react";

import { LaunchGateNotice, readableApiError, useLaunchGate } from "@/src/shared/launch-gate";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { schedulePost, type Channel } from "./api";

interface ScheduleFormProps {
  channels: Channel[];
  /** Called after a successful schedule so the queue can refresh. */
  onScheduled: () => void;
}

/** Real form: queue a finished job to publish at a future time. */
export function ScheduleForm({ channels, onScheduled }: ScheduleFormProps) {
  const { getToken } = useAuth();
  const publishGate = useLaunchGate().gate.publishing;
  const [jobId, setJobId] = React.useState("");
  const [platform, setPlatform] = React.useState("");
  const [publishAt, setPublishAt] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [ok, setOk] = React.useState("");

  React.useEffect(() => {
    if (!platform && channels[0]) setPlatform(channels[0].provider);
  }, [channels, platform]);

  const onSubmit = React.useCallback(async () => {
    setBusy(true);
    setError("");
    setOk("");
    try {
      const token = (await getToken()) ?? undefined;
      // `datetime-local` yields local wall-clock time; normalize to UTC ISO.
      const iso = new Date(publishAt).toISOString();
      const res = await schedulePost(
        jobId.trim(),
        { platforms: [platform], scheduled_at: iso },
        { token, idempotencyKey: crypto.randomUUID() },
      );
      setOk(`Scheduled for ${platform} · status ${res.status}.`);
      setJobId("");
      setPublishAt("");
      onScheduled();
    } catch (err) {
      setError(readableApiError(err, "Failed to schedule."));
    } finally {
      setBusy(false);
    }
  }, [getToken, jobId, platform, publishAt, onScheduled]);

  const validDate = publishAt && !Number.isNaN(new Date(publishAt).getTime());
  const canSubmit = !busy && publishGate.open && jobId.trim() !== "" && platform !== "" && Boolean(validDate);

  return (
    <Card>
      <CardContent className="space-y-4 py-5">
        <div className="flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-primary" aria-hidden />
          <h2 className="font-semibold">Schedule a post</h2>
        </div>

        <LaunchGateNotice gate={publishGate} />

        <div className="space-y-1.5">
          <Label htmlFor="sf-job">Job ID</Label>
          <Input
            id="sf-job"
            placeholder="job_..."
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="sf-platform">Platform</Label>
          <Select
            id="sf-platform"
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            disabled={channels.length === 0}
          >
            {channels.length === 0 ? (
              <option value="">No connected channels</option>
            ) : (
              channels.map((c) => (
                <option key={c.provider} value={c.provider}>
                  {c.provider}
                  {c.external_account_id ? ` · @${c.external_account_id}` : ""}
                </option>
              ))
            )}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="sf-when">Publish at</Label>
          <Input
            id="sf-when"
            type="datetime-local"
            value={publishAt}
            onChange={(e) => setPublishAt(e.target.value)}
          />
        </div>

        <Button onClick={() => void onSubmit()} disabled={!canSubmit}>
          {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
          Schedule
        </Button>

        {ok && <p className="text-sm text-success">{ok}</p>}
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
