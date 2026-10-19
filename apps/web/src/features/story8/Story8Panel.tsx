"use client";

import * as React from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { signInHref } from "@/lib/auth-redirect";
import { useSignedInState } from "@/lib/auth-state";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  STORY_DONE,
  STORY_FAILED,
  getStory,
  planStory,
  startStory,
  type StoryJob,
  type StoryMode,
  type StoryPlan,
  type StoryPrice,
} from "./api";

const POLL_MS = 4000;

function priceLabel(price: StoryPrice): string {
  const standard = `${price.standard_credits} credit${price.standard_credits === 1 ? "" : "s"}`;
  return price.ai_video_credits > 0 ? `${standard} + ${price.ai_video_credits} AI-video credits` : standard;
}

/** Topic or script in, eight lines out (editable), one tap to make it, priced first. */
export function Story8Panel({ characterId = null }: Readonly<{ characterId?: string | null }>) {
  const { isLoaded, isSignedIn } = useSignedInState();
  const getApiToken = useApiToken();
  const [text, setText] = React.useState("");
  const [asScript, setAsScript] = React.useState(false);
  const [plan, setPlan] = React.useState<StoryPlan | null>(null);
  const [lines, setLines] = React.useState<string[]>([]);
  const [job, setJob] = React.useState<StoryJob | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!job || job.state === STORY_DONE || job.state === STORY_FAILED) return undefined;
    const timer = setTimeout(async () => {
      try {
        setJob(await getStory(job.job_id, { token: await getApiToken() }));
      } catch (err) {
        setError(friendlyErrorMessage(err, "We lost track of this story; open your reels to find it."));
      }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [getApiToken, job]);

  if (isLoaded && !isSignedIn) {
    return (
      <p className="text-sm">
        <Link className="underline" href={signInHref("/story")}>Sign in</Link> to make a story.
      </p>
    );
  }

  async function onPlan(event: React.FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      const body = asScript ? { script: text, character_id: characterId } : { topic: text, character_id: characterId };
      const next = await planStory(body, { token: await getApiToken() });
      setPlan(next);
      setLines([...next.lines]);
    } catch (err) {
      setError(friendlyErrorMessage(err, "We could not write this story."));
    } finally {
      setBusy(false);
    }
  }

  async function onMake(mode: StoryMode) {
    if (!plan) return;
    setBusy(true);
    setError("");
    try {
      const token = await getApiToken();
      const started = await startStory({ lines, mode, quoted: plan.quote[mode], character_id: characterId }, { token });
      setJob(await getStory(started.job_id, { token }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "We could not start this story."));
    } finally {
      setBusy(false);
    }
  }

  if (job) {
    return (
      <section aria-labelledby="story-result" className="space-y-4">
        <h2 id="story-result" className="text-lg font-semibold">
          {job.state === STORY_DONE ? "Your story is ready" : job.state === STORY_FAILED ? "This story failed" : "Making your story"}
        </h2>
        {job.state === STORY_DONE && job.video_url ? (
          <video className="aspect-[9/16] w-full max-w-sm rounded-2xl" src={job.video_url} poster={job.poster_url} controls playsInline />
        ) : null}
        {job.state === STORY_FAILED ? <p role="alert">{job.error || "Everything it held was refunded."}</p> : null}
        <ol className="grid grid-cols-4 gap-2">
          {job.frames.map((frame) => (
            <li key={frame.index} className="space-y-1 text-xs">
              {frame.image_url ? (
                <img className="aspect-[9/16] w-full rounded-lg object-cover" src={frame.image_url} alt={frame.line} />
              ) : (
                <div className="aspect-[9/16] w-full rounded-lg bg-muted" aria-label={`Frame ${frame.index + 1} is on its way`} />
              )}
              {typeof frame.identity_score === "number" ? <span>Match {Math.round(frame.identity_score * 100)}%</span> : null}
            </li>
          ))}
        </ol>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <form onSubmit={onPlan} className="space-y-3">
        <label className="block text-sm font-medium" htmlFor="story-text">
          {asScript ? "Your script" : "What is the story about?"}
        </label>
        <textarea
          id="story-text"
          className="min-h-24 w-full rounded-xl border border-border bg-background p-3"
          value={text}
          maxLength={asScript ? 2400 : 300}
          onChange={(event) => setText(event.target.value)}
        />
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={busy || !text.trim()}>Write the 8 frames</Button>
          <button type="button" className="text-sm underline" onClick={() => setAsScript(!asScript)}>
            {asScript ? "Use a topic instead" : "I have a script"}
          </button>
        </div>
      </form>
      {plan ? (
        <section aria-labelledby="story-lines" className="space-y-3">
          <h2 id="story-lines" className="text-lg font-semibold">Your 8 frames</h2>
          <ol className="space-y-2">
            {lines.map((line, index) => (
              <li key={plan.frames[index]?.beat ?? index}>
                <label className="sr-only" htmlFor={`line-${index}`}>{`Frame ${index + 1}`}</label>
                <input
                  id={`line-${index}`}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
                  value={line}
                  maxLength={220}
                  onChange={(event) => setLines(lines.map((l, i) => (i === index ? event.target.value : l)))}
                />
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap gap-3">
            <Button disabled={busy} onClick={() => void onMake("frames")}>
              Make it with moving frames: {priceLabel(plan.quote.frames)}
            </Button>
            <Button variant="outline" disabled={busy} onClick={() => void onMake("animated")}>
              Animate every frame: {priceLabel(plan.quote.animated)}
            </Button>
          </div>
        </section>
      ) : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
