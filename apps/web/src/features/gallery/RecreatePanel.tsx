"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { signUpHref } from "@/lib/auth-redirect";
import { useSignedInState } from "@/lib/auth-state";
import { useApiToken } from "@/lib/use-api-token";
import { quoteForPlan, startPlan } from "@/src/features/presets-shelf/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { getGalleryItem, getRemix, linkRemix, recreatePlan, type GalleryItem } from "./api";

export const REMIX_POLL_MS = 10000;

export interface RecreatePanelProps {
  readonly itemId: string;
  readonly imageKey?: string;
  readonly initialItem?: GalleryItem;
}

type Phase = "input" | "priced" | "started";

/** Recreate: the item's settings with your own topic or link. Price first, then Make. */
export function RecreatePanel({ itemId, imageKey = "", initialItem }: RecreatePanelProps) {
  const { isLoaded, isSignedIn } = useSignedInState();
  const getApiToken = useApiToken();
  const [item, setItem] = React.useState<GalleryItem | null>(initialItem ?? null);
  const [subject, setSubject] = React.useState("");
  const [phase, setPhase] = React.useState<Phase>("input");
  const [price, setPrice] = React.useState<{ credits: number; affordable: boolean; unit: string } | null>(null);
  const [jobId, setJobId] = React.useState("");
  const [counted, setCounted] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (initialItem) return;
    getGalleryItem(itemId)
      .then(setItem)
      .catch(() => setError("This gallery item is not available."));
  }, [initialItem, itemId]);

  React.useEffect(() => {
    if (phase !== "started" || !jobId || counted) return;
    let live = true;
    const tick = async () => {
      try {
        const token = await getApiToken();
        const view = await getRemix(jobId, { token });
        if (live && view.counted) setCounted(true);
      } catch {
        /* the result link is always there */
      }
    };
    const timer = window.setInterval(tick, REMIX_POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [counted, getApiToken, jobId, phase]);

  async function plan() {
    const token = await getApiToken();
    const body = { subject, ...(imageKey ? { image_key: imageKey } : {}) };
    return { token, plan: await recreatePlan(itemId, body, { token }) };
  }

  async function onPrice(event: React.FormEvent) {
    event.preventDefault();
    if (!subject.trim()) return;
    setBusy(true);
    setError("");
    try {
      const { token, plan: next } = await plan();
      const animates = next.route !== "jobs" && next.body.mode === "i2v";
      const quote = await quoteForPlan(next, animates, { token });
      setPrice({ ...quote, unit: next.route === "jobs" ? "credit" : "AI-video credit" });
      setPhase("priced");
    } catch (err) {
      setError(friendlyErrorMessage(err, "We could not price this."));
    } finally {
      setBusy(false);
    }
  }

  async function onMake() {
    setBusy(true);
    setError("");
    try {
      const { token, plan: next } = await plan();
      const idempotencyKey = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${itemId}`;
      const id = await startPlan(next, { token, idempotencyKey });
      setJobId(id);
      await linkRemix(itemId, id, { token });
      setPhase("started");
    } catch (err) {
      setError(friendlyErrorMessage(err, "We could not start this."));
    } finally {
      setBusy(false);
    }
  }

  if (!item) return error ? <p role="alert">{error}</p> : <p className="text-sm text-muted-foreground">Loading</p>;
  const here = `/gallery?recreate=${encodeURIComponent(item.id)}`;
  return (
    <section aria-labelledby="recreate-title" className="mx-auto max-w-md space-y-4">
      <video
        className="aspect-[9/16] w-full rounded-2xl object-cover"
        src={item.preview_url}
        poster={item.poster_url}
        autoPlay
        muted
        loop
        playsInline
        aria-label={`${item.title || "Gallery reel"} preview`}
      />
      <h2 id="recreate-title" className="text-xl font-semibold">Recreate {item.title ? `"${item.title}"` : "this reel"}</h2>
      <p className="text-sm text-muted-foreground">Same look and settings, your own topic or link.</p>
      {isLoaded && !isSignedIn ? (
        <Button asChild className="w-full">
          <Link href={signUpHref(here)}>Sign up with your email to recreate this</Link>
        </Button>
      ) : phase === "input" ? (
        <form onSubmit={onPrice} className="space-y-3">
          <label className="block text-sm font-medium" htmlFor="recreate-subject">Your topic or link</label>
          <input
            id="recreate-subject"
            className="w-full rounded-xl border border-border bg-background px-3 py-2"
            value={subject}
            maxLength={600}
            onChange={(e) => setSubject(e.target.value)}
          />
          <Button type="submit" className="w-full" disabled={busy || !subject.trim()}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} See the price
          </Button>
        </form>
      ) : phase === "priced" && price ? (
        <div className="space-y-3">
          <p data-testid="recreate-price">Uses {price.credits} {price.credits === 1 ? price.unit : `${price.unit}s`}.</p>
          {price.affordable ? (
            <Button className="w-full" onClick={onMake} disabled={busy}>
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Make it
            </Button>
          ) : (
            <Button asChild className="w-full">
              <Link href="/pricing">Top up to make it</Link>
            </Button>
          )}
          <Button variant="ghost" className="w-full" onClick={() => setPhase("input")} disabled={busy}>
            Change the topic
          </Button>
        </div>
      ) : (
        <div className="space-y-2" aria-live="polite">
          <p>Rendering your version. {counted ? "It now counts as a remix of this reel." : ""}</p>
          <Link className="underline underline-offset-4" href={`/jobs/${encodeURIComponent(jobId)}`}>Open the result</Link>
        </div>
      )}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
