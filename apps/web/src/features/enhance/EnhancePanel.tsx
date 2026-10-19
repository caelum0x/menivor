"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { listOwnFinishedReels, type OwnReel } from "@/src/features/gallery/api";
import { getEnhance, quoteVideo, startVideo, upscaleStill, type EnhanceJob, type VideoOp, type VideoQuote } from "./api";

const POLL_MS = 4000;
const DONE = 1;
const FAILED = -1;

/** Pick a finished reel, then one tap: a 4x still, a sharper video or smoother motion (priced first). */
export function EnhancePanel() {
  const getApiToken = useApiToken();
  const [reels, setReels] = React.useState<readonly OwnReel[] | null>(null);
  const [picked, setPicked] = React.useState<string>("");
  const [quote, setQuote] = React.useState<VideoQuote | null>(null);
  const [job, setJob] = React.useState<EnhanceJob | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const mine = await listOwnFinishedReels({ token: await getApiToken() });
        if (live) setReels(mine);
      } catch (err) {
        if (live) setError(friendlyErrorMessage(err, "Your reels could not load."));
      }
    })();
    return () => {
      live = false;
    };
  }, [getApiToken]);

  React.useEffect(() => {
    if (!job || job.state === DONE || job.state === FAILED) return undefined;
    const timer = setTimeout(async () => {
      try {
        setJob(await getEnhance(job.job_id, { token: await getApiToken() }));
      } catch (err) {
        setError(friendlyErrorMessage(err, "We lost track of this job."));
      }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [getApiToken, job]);

  async function run(action: () => Promise<{ job_id: string }>) {
    setBusy(true);
    setError("");
    try {
      const token = await getApiToken();
      const started = await action();
      setQuote(null);
      setJob(await getEnhance(started.job_id, { token }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "This could not start."));
    } finally {
      setBusy(false);
    }
  }

  async function onQuote(op: VideoOp) {
    setBusy(true);
    setError("");
    try {
      setQuote(await quoteVideo(picked, op, { token: await getApiToken() }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "This is not available right now."));
    } finally {
      setBusy(false);
    }
  }

  if (reels === null) return error ? <p role="alert">{error}</p> : <p className="text-sm text-muted-foreground">Loading</p>;
  if (reels.length === 0) return <p className="text-sm">Finish a reel first; then you can make it sharper here.</p>;
  return (
    <div className="space-y-4">
      <label className="block text-sm font-medium" htmlFor="enhance-reel">Reel</label>
      <select
        id="enhance-reel"
        className="w-full rounded-lg border border-border bg-background px-3 py-2"
        value={picked}
        onChange={(event) => {
          setPicked(event.target.value);
          setQuote(null);
          setJob(null);
        }}
      >
        <option value="">Pick a finished reel</option>
        {reels.map((reel) => (
          <option key={reel.job_id} value={reel.job_id}>{reel.title || reel.job_id}</option>
        ))}
      </select>
      {picked ? (
        <div className="flex flex-wrap gap-3">
          <Button disabled={busy} onClick={() => void run(async () => upscaleStill(picked, { token: await getApiToken() }))}>
            Sharper cover (4x, free)
          </Button>
          <Button variant="outline" disabled={busy} onClick={() => void onQuote("upscale")}>Sharper video</Button>
          <Button variant="outline" disabled={busy} onClick={() => void onQuote("smooth")}>Smoother motion</Button>
        </div>
      ) : null}
      {quote ? (
        <div className="flex items-center gap-3 rounded-xl border border-border p-3 text-sm">
          <span>{quote.ai_video_credits} AI-video credits</span>
          <Button
            disabled={busy}
            onClick={() => void run(async () => startVideo(picked, quote.op, quote.ai_video_credits, { token: await getApiToken() }))}
          >
            Start
          </Button>
        </div>
      ) : null}
      {job ? (
        <div aria-live="polite" className="text-sm">
          {job.state === DONE && job.result_url ? (
            <a className="underline" href={job.result_url} download>
              Download{job.output ? ` (${job.output[0]}x${job.output[1]})` : ""}
            </a>
          ) : job.state === FAILED ? (
            <p role="alert">{job.error || "It failed."}{job.refunded ? " Your credits are back." : ""}</p>
          ) : (
            <p>Working on it</p>
          )}
        </div>
      ) : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
