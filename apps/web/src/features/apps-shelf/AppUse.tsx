"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { listMusic, presignAndUpload } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { quoteForPlan, startPlan } from "@/src/features/presets-shelf/api";
import { getAppRun, planApp, priceText, quoteApp, runApp, type AppInputs, type AppRun, type ShelfApp } from "./api";

const POLL_MS = 3000;
const IMAGE_KINDS = new Set(["image", "image_text", "image_choice", "two_images"]);
const VIDEO_KINDS = new Set(["video_music", "video_text"]);
const TEXT_KINDS = new Set(["link", "topic", "text", "image_text", "video_text"]);

/** One input screen for one app: fill it, see the price, press once. */
export function AppUse({ app }: Readonly<{ app: ShelfApp }>) {
  const getApiToken = useApiToken();
  const [tracks, setTracks] = React.useState<readonly { id: string; name: string }[]>([]);
  const [inputs, setInputs] = React.useState<AppInputs>({});
  const [price, setPrice] = React.useState<string>("");
  const [credits, setCredits] = React.useState<number | null>(null);
  const [run, setRun] = React.useState<AppRun | null>(null);
  const [started, setStarted] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const kind = app.input.kind;

  React.useEffect(() => {
    if (kind !== "video_music") return undefined;
    let live = true;
    void (async () => {
      try {
        const list = await listMusic({ token: await getApiToken() });
        if (live) setTracks(list.map((t) => ({ id: String(t.id), name: String(t.name ?? t.id) })));
      } catch (err) {
        if (live) setError(friendlyErrorMessage(err, "The music library could not load."));
      }
    })();
    return () => {
      live = false;
    };
  }, [getApiToken, kind]);

  React.useEffect(() => {
    if (!run || run.state === 1 || run.state === -1) return undefined;
    const timer = setTimeout(async () => setRun(await getAppRun(run.job_id, { token: await getApiToken() })), POLL_MS);
    return () => clearTimeout(timer);
  }, [getApiToken, run]);

  async function upload(field: keyof AppInputs, file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const token = await getApiToken();
      const { key } = await presignAndUpload(file, { token });
      setInputs((current) => ({ ...current, [field]: key }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "That upload did not finish."));
    } finally {
      setBusy(false);
    }
  }

  async function onPrice(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const token = await getApiToken();
      if (app.price.priced_by === "create") {
        const plan = await planApp(app.id, inputs, { token });
        const quote = await quoteForPlan(plan, false, { token });
        setCredits(quote.credits);
        setPrice(`${quote.credits} credit${quote.credits === 1 ? "" : "s"}`);
      } else {
        const quote = await quoteApp(app.id, inputs, { token });
        setCredits(quote.credits ?? 0);
        setPrice(priceText(quote));
      }
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
      const token = await getApiToken();
      if (app.price.priced_by === "create") {
        const plan = await planApp(app.id, inputs, { token });
        setStarted(await startPlan(plan, { token }));
      } else {
        const job = await runApp(app.id, inputs, credits ?? 0, { token });
        setRun(await getAppRun(job.job_id, { token }));
      }
    } catch (err) {
      setError(friendlyErrorMessage(err, "We could not start this."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby={`app-${app.id}`} className="space-y-3">
      <h2 id={`app-${app.id}`} className="text-lg font-semibold">{app.name}</h2>
      <form onSubmit={onPrice} className="space-y-3">
        {IMAGE_KINDS.has(kind) ? (
          <label className="block text-sm">
            {app.input.label}
            <input className="mt-1 block" type="file" accept="image/*" onChange={(e) => void upload("image_key", e.target.files?.[0])} />
          </label>
        ) : null}
        {kind === "two_images" ? (
          <label className="block text-sm">
            {app.input.second_label}
            <input className="mt-1 block" type="file" accept="image/*" onChange={(e) => void upload("image_key_2", e.target.files?.[0])} />
          </label>
        ) : null}
        {VIDEO_KINDS.has(kind) ? (
          <label className="block text-sm">
            {app.input.label}
            <input className="mt-1 block" type="file" accept="video/*" onChange={(e) => void upload("video_key", e.target.files?.[0])} />
          </label>
        ) : null}
        {kind === "video_music" ? (
          <label className="block text-sm">
            Track
            <select className="mt-1 block rounded border border-border bg-background px-2 py-1" value={inputs.music_id ?? ""}
              onChange={(e) => setInputs({ ...inputs, music_id: e.target.value })}>
              <option value="">Pick a track</option>
              {tracks.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
        ) : null}
        {kind === "image_choice" ? (
          <fieldset className="flex flex-wrap gap-2 text-sm">
            <legend className="sr-only">Light</legend>
            {(app.input.choices ?? []).map((choice) => (
              <label key={choice} className="flex items-center gap-1">
                <input type="radio" name={`${app.id}-choice`} value={choice} checked={inputs.choice === choice}
                  onChange={() => setInputs({ ...inputs, choice })} />
                {choice}
              </label>
            ))}
          </fieldset>
        ) : null}
        {TEXT_KINDS.has(kind) ? (
          <label className="block text-sm">
            {kind === "image_text" || kind === "video_text" ? app.input.text_label : app.input.label}
            <input className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2" value={inputs.text ?? ""}
              maxLength={600} onChange={(e) => setInputs({ ...inputs, text: e.target.value })} />
          </label>
        ) : null}
        <Button type="submit" variant="outline" disabled={busy}>See the price</Button>
      </form>
      {price ? (
        <div className="flex items-center gap-3 text-sm">
          <span>{price}</span>
          <Button disabled={busy} onClick={() => void onMake()}>Make it</Button>
        </div>
      ) : null}
      {started ? <p className="text-sm">Started. It will appear in your reels when it is ready.</p> : null}
      {run?.state === 1 ? (
        <div className="space-y-2 text-sm">
          {run.outputs.map((url) => <a key={url} className="block underline" href={url} download>Download</a>)}
          {run.result && typeof run.result.score === "number" ? <p>{`Hook score ${Math.round(Number(run.result.score) * 100)} of 100`}</p> : null}
        </div>
      ) : null}
      {run?.state === -1 ? <p role="alert">{run.error}{run.refunded ? " Your credits are back." : ""}</p> : null}
      {run && run.state !== 1 && run.state !== -1 ? <p className="text-sm">Working on it</p> : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
