"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { signUpHref } from "@/lib/auth-redirect";
import { useSignedInState } from "@/lib/auth-state";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { PresetInputs, type PresetInputsValue } from "@/src/features/my-characters/PresetInputs";
import { recordIdentityScore } from "@/src/features/my-characters/api";
import {
  formatSeconds,
  getRun,
  getTile,
  planPreset,
  quotePlan,
  recordRun,
  startPlan,
  type PresetRunView,
  type PresetTile,
} from "./api";

export const RUN_POLL_MS = 5000;

export interface PresetUseProps {
  readonly presetId: string;
  /** An image the caller already uploaded (animate-image presets). */
  readonly imageKey?: string;
  /** Test seam: the tile is fetched when not given. */
  readonly initialTile?: PresetTile;
  /** Test seam for the tap time. */
  readonly now?: () => Date;
}

type Phase = "input" | "priced" | "running" | "done";

/**
 * One preset, one input, one button. The price comes first (MG3); pressing
 * Make starts the render through the normal create route, and the time from
 * the tile tap to the first result is measured and shown for this run.
 */
export function PresetUse({ presetId, imageKey = "", initialTile, now = () => new Date() }: PresetUseProps) {
  const { isLoaded, isSignedIn } = useSignedInState();
  const getApiToken = useApiToken();
  const openedAt = React.useRef(now().toISOString());
  const [tile, setTile] = React.useState<PresetTile | null>(initialTile ?? null);
  const [subject, setSubject] = React.useState("");
  const [phase, setPhase] = React.useState<Phase>("input");
  const [price, setPrice] = React.useState<{ credits: number; affordable: boolean; route?: string } | null>(null);
  const [jobId, setJobId] = React.useState("");
  const [run, setRun] = React.useState<PresetRunView | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [inputs, setInputs] = React.useState<PresetInputsValue>({ brandKitId: "", characterId: "" });
  const scored = React.useRef(false);

  React.useEffect(() => {
    if (initialTile) return;
    getTile(presetId)
      .then(setTile)
      .catch(() => setError("This preset is not available."));
  }, [initialTile, presetId]);

  React.useEffect(() => {
    if (phase !== "running" || !jobId) return;
    let live = true;
    const tick = async () => {
      try {
        const token = await getApiToken();
        const view = await getRun(jobId, { token });
        if (!live) return;
        setRun(view);
        if (view.seconds_to_result !== null) {
          setPhase("done");
          if (inputs.characterId && tile && !scored.current) {
            scored.current = true;
            // MH4: record how close this render stays to the character (preset x model).
            void recordIdentityScore(
              inputs.characterId,
              { job_id: jobId, preset_id: tile.id, model: price?.route || tile.kind },
              { token },
            ).catch(() => undefined);
          }
        }
      } catch {
        /* keep polling; the job page link is always there */
      }
    };
    void tick();
    const timer = window.setInterval(tick, RUN_POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [getApiToken, inputs.characterId, jobId, phase, price?.route, tile]);

  const needsImage = Boolean(tile?.inputs.includes("image")) && !inputs.characterId;
  const planBody = () => ({
    subject,
    ...(imageKey ? { image_key: imageKey } : {}),
    ...(inputs.brandKitId ? { brand_kit_id: inputs.brandKitId } : {}),
    ...(inputs.characterId ? { character_id: inputs.characterId } : {}),
  });
  const unit = tile?.credit_kind === "ai_video" ? "AI-video credit" : "credit";

  async function onPrice(event: React.FormEvent) {
    event.preventDefault();
    if (!tile || !subject.trim()) return;
    setBusy(true);
    setError("");
    try {
      const token = await getApiToken();
      const plan = await planPreset(tile.id, planBody(), { token });
      setPrice(await quotePlan(tile, plan, { token }));
      setPhase("priced");
    } catch (err) {
      setError(friendlyErrorMessage(err, "We could not price this preset."));
    } finally {
      setBusy(false);
    }
  }

  async function onMake() {
    if (!tile) return;
    setBusy(true);
    setError("");
    try {
      const token = await getApiToken();
      const plan = await planPreset(tile.id, planBody(), { token });
      const idempotencyKey = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${tile.id}`;
      const id = await startPlan(plan, { token, idempotencyKey });
      setJobId(id);
      await recordRun(tile.id, { job_id: id, opened_at: openedAt.current }, { token });
      setPhase("running");
    } catch (err) {
      setError(friendlyErrorMessage(err, "We could not start this preset."));
    } finally {
      setBusy(false);
    }
  }

  if (!tile) {
    return error ? <p role="alert">{error}</p> : <p className="text-sm text-muted-foreground">Loading preset</p>;
  }
  const here = `/presets-gallery?use=${encodeURIComponent(tile.id)}`;
  return (
    <section aria-labelledby="preset-use-title" className="mx-auto max-w-md space-y-4">
      <video
        className="aspect-[9/16] w-full rounded-2xl object-cover"
        src={tile.preview.loop_url}
        poster={tile.preview.poster_url}
        autoPlay
        muted
        loop
        playsInline
        aria-label={`${tile.name} preview`}
      />
      <h2 id="preset-use-title" className="text-xl font-semibold">{tile.name}</h2>
      <p className="text-sm text-muted-foreground">{tile.blurb}</p>
      {isLoaded && !isSignedIn ? (
        <Button asChild className="w-full">
          <Link href={signUpHref(here)}>Sign up with your email to use this preset</Link>
        </Button>
      ) : phase === "input" ? (
        <form onSubmit={onPrice} className="space-y-3">
          <label className="block text-sm font-medium" htmlFor="preset-subject">
            Your topic or link
          </label>
          <input
            id="preset-subject"
            className="w-full rounded-xl border border-border bg-background px-3 py-2"
            value={subject}
            maxLength={600}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="A new espresso bar on our street"
          />
          {isSignedIn ? (
            <PresetInputs allowCharacter={tile.kind === "model"} value={inputs} onChange={setInputs} />
          ) : null}
          {needsImage && !imageKey ? (
            <p className="text-sm text-muted-foreground">This preset animates your own image. Add one first.</p>
          ) : null}
          <Button type="submit" className="w-full" disabled={busy || !subject.trim() || (needsImage && !imageKey)}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} See the price
          </Button>
        </form>
      ) : phase === "priced" && price ? (
        <div className="space-y-3">
          <p data-testid="preset-price">
            Uses {price.credits} {price.credits === 1 ? unit : `${unit}s`}.
          </p>
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
          {run?.seconds_to_result !== null && run?.seconds_to_result !== undefined ? (
            <p data-testid="preset-timing">
              First result in {formatSeconds(run.seconds_to_result)} (target {formatSeconds(run.target_seconds)}).
            </p>
          ) : (
            <p>Rendering. The clock started when you opened this preset.</p>
          )}
          <Link className="underline underline-offset-4" href={`/jobs/${encodeURIComponent(jobId)}`}>
            Open the result
          </Link>
        </div>
      )}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
