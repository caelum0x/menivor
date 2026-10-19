"use client";

import * as React from "react";
import Link from "next/link";
import { Languages, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ChipToggle, ErrorText, errorMessage, toggleIn, useRequestOptions } from "@/src/features/ad-studio/shared";
import {
  MAX_TARGETS,
  getOptions,
  planTranslation,
  recentTranslations,
  submitTranslation,
  type StudioRender,
  type TranslateOptions,
} from "./api";

const CARD = "rounded-2xl border border-white/10 bg-white/[0.03] p-4 shadow-[inset_0_1px_0_hsl(0_0%_100%/0.05)]";
export const VOICE_RULE = "Only your AI actors' designed voices. No voice is ever cloned.";

const STATUS: Record<string, string> = {
  planned: "Priced",
  pending_approval: "Waiting for approval",
  queued: "Queued",
  running: "Rendering",
  done: "Done",
  failed: "Failed",
  rejected: "Rejected",
};

function money(v: unknown): string {
  return `$${Number(v || 0).toFixed(2)}`;
}

function RenderRow({ render }: { render: StudioRender }) {
  const outputs = (render.result.outputs as { code: string; label: string; video_url: string }[] | undefined) ?? [];
  return (
    <li className="space-y-1 rounded-xl border border-white/10 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>{render.title}</span>
        <Badge variant={render.status === "done" ? "success" : render.status === "failed" ? "destructive" : "secondary"}>
          {STATUS[render.status] ?? render.status}
        </Badge>
      </div>
      {outputs.length ? (
        <div className="flex flex-wrap gap-3">
          {outputs.map((o) => (
            <a key={o.code} href={o.video_url} className="text-primary underline-offset-2 hover:underline" target="_blank" rel="noreferrer">
              {o.label}
            </a>
          ))}
        </div>
      ) : null}
      {render.error ? <p className="text-xs text-destructive">{render.error}</p> : null}
    </li>
  );
}

/** Lip-sync translation: own video + a designed actor voice + languages -> priced plan -> approval. */
export function TranslateWorkspace() {
  const requestOptions = useRequestOptions();
  const [opts, setOpts] = React.useState<TranslateOptions | null>(null);
  const [recent, setRecent] = React.useState<StudioRender[]>([]);
  const [video, setVideo] = React.useState("");
  const [actor, setActor] = React.useState("");
  const [targets, setTargets] = React.useState<string[]>([]);
  const [engine, setEngine] = React.useState<"kling" | "infinitetalk">("kling");
  const [captions, setCaptions] = React.useState(true);
  const [seconds, setSeconds] = React.useState("15");
  const [transcript, setTranscript] = React.useState("");
  const [render, setRender] = React.useState<StudioRender | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const o = await requestOptions();
      const [options, renders] = await Promise.all([getOptions(o), recentTranslations(o)]);
      setOpts(options);
      setRecent(renders);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [requestOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const ready = Boolean(video && actor && targets.length && Number(seconds) > 0);

  async function price() {
    setBusy(true);
    setError("");
    try {
      setRender(
        await planTranslation(
          { video_url: video, actor_id: actor, targets, seconds: Number(seconds), engine, captions, transcript },
          await requestOptions(),
        ),
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!render) return;
    setError("");
    try {
      const sent = await submitTranslation(render.id, await requestOptions());
      setRender(sent);
      setRecent((r) => [sent, ...r.filter((x) => x.id !== sent.id)]);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const plan = render?.plan as
    | { steps?: string[]; usd_per_language?: number; targets?: { code: string; label: string }[] }
    | undefined;

  return (
    <div className="space-y-6" data-testid="translate-page">
      <header className="space-y-2">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Languages className="size-6 text-primary" aria-hidden /> Lip-sync translate
        </h1>
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="size-4 text-primary" aria-hidden /> {VOICE_RULE}
        </p>
      </header>
      <ErrorText message={error} />

      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <section className={`${CARD} space-y-4`} aria-label="Translation">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="tr-video">Video</Label>
              <Select id="tr-video" value={video} onChange={(e) => setVideo(e.target.value)}>
                <option value="">Pick one of your videos</option>
                {opts?.videos.map((v) => <option key={v.id} value={v.url}>{v.title || v.id}</option>)}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tr-voice">Voice</Label>
              <Select id="tr-voice" value={actor} onChange={(e) => setActor(e.target.value)}>
                <option value="">Pick an actor voice</option>
                {opts?.voices.map((v) => (
                  <option key={v.actor_id} value={v.actor_id} disabled={!v.ready}>
                    {v.ready ? v.name : `${v.name} (design a voice first)`}
                  </option>
                ))}
              </Select>
              {opts?.voices.some((v) => !v.ready) ? (
                <p className="text-xs text-muted-foreground">
                  Some actors have no voice yet. <Link href="/actors" className="underline">Design a voice first</Link>.
                </p>
              ) : null}
            </div>
          </div>
          <div className="space-y-1.5">
            <p className="text-sm font-medium">Languages ({targets.length}/{MAX_TARGETS})</p>
            <div className="flex flex-wrap gap-1.5">
              {opts?.languages.map((l) => (
                <ChipToggle
                  key={l.code}
                  selected={targets.includes(l.code)}
                  disabled={!targets.includes(l.code) && targets.length >= MAX_TARGETS}
                  onToggle={() => setTargets((t) => toggleIn(t, l.code))}
                >
                  {l.label}
                </ChipToggle>
              ))}
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="tr-engine">Lip-sync</Label>
              <Select id="tr-engine" value={engine} onChange={(e) => setEngine(e.target.value as "kling" | "infinitetalk")}>
                {opts?.engines.map((e) => (
                  <option key={e.id} value={e.id}>{e.label}{e.configured ? "" : " (not set up)"}</option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tr-seconds">Seconds</Label>
              <Input id="tr-seconds" type="number" min={1} max={120} value={seconds} onChange={(e) => setSeconds(e.target.value)} />
            </div>
            <label className="flex items-center gap-2 self-end pb-2 text-sm">
              <input type="checkbox" checked={captions} onChange={(e) => setCaptions(e.target.checked)} /> Burned captions
            </label>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tr-transcript">Transcript (optional)</Label>
            <Textarea id="tr-transcript" rows={3} value={transcript} maxLength={8000} onChange={(e) => setTranscript(e.target.value)}
              placeholder="Leave empty and we transcribe the video." />
          </div>
          {!render ? (
            <Button disabled={!ready || busy} onClick={price}>{busy ? "Pricing..." : "Price it"}</Button>
          ) : null}
        </section>

        <section className={`${CARD} space-y-3`} aria-label="Price">
          <h2 className="text-lg font-semibold">Price</h2>
          {render && plan ? (
            <>
              <ol className="list-decimal space-y-0.5 pl-5 text-sm text-muted-foreground">
                {plan.steps?.map((s) => <li key={s}>{s}</li>)}
              </ol>
              <p className="text-sm">{money(plan.usd_per_language)} per language, {plan.targets?.length ?? 0} languages.</p>
              <p className="text-base font-medium" data-testid="translate-total">
                Total {money(render.quote_usd)} ({render.credits} AI-video credits)
              </p>
              {render.status === "planned" ? (
                <Button variant="outline" onClick={submit}>Send for approval</Button>
              ) : (
                <p role="status" className="text-sm">
                  Waiting for approval. <Link className="underline" href="/approvals">Open approvals</Link>
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Pick a video, a voice and languages to see the price. Nothing is spent until you approve.</p>
          )}
          <h2 className="pt-2 text-lg font-semibold">Recent</h2>
          {recent.length ? <ul className="space-y-2">{recent.map((r) => <RenderRow key={r.id} render={r} />)}</ul> : (
            <p className="text-sm text-muted-foreground">No translations yet.</p>
          )}
        </section>
      </div>
    </div>
  );
}
