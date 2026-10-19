"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { presignAndUpload } from "@/lib/api";
import { presenterLive } from "@/lib/styles/catalog";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { apiRequest } from "@/src/shared/api";
import { listMyCharacters, type MyCharacter } from "@/src/features/my-characters/api";

interface SceneOption {
  readonly id: string;
  readonly name: string;
  readonly blurb: string;
  readonly needs_product: boolean;
}

interface SceneRun {
  readonly job_id: string;
  readonly state: number;
  readonly video_url: string;
  readonly error: string;
  readonly refunded: boolean;
}

/**
 * Talking scenes (MH6). Renders nothing until presenters are live
 * (`NEXT_PUBLIC_PRESENTER_LIVE`, claims rule 5); the API answers 404 until then too.
 */
export function ScenePanel({ characterId: fixed = "", live = presenterLive() }: Readonly<{ characterId?: string; live?: boolean }>) {
  const getApiToken = useApiToken();
  const [characters, setCharacters] = React.useState<readonly MyCharacter[]>([]);
  const [characterId, setCharacterId] = React.useState(fixed);
  const [scenes, setScenes] = React.useState<readonly SceneOption[]>([]);
  const [scene, setScene] = React.useState<SceneOption | null>(null);
  const [script, setScript] = React.useState("");
  const [productKey, setProductKey] = React.useState("");
  const [credits, setCredits] = React.useState<number | null>(null);
  const [run, setRun] = React.useState<SceneRun | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!live) return undefined;
    let active = true;
    apiRequest<{ scenes: SceneOption[] }>("/scenes", { anonymous: true })
      .then((data) => active && setScenes(data.scenes ?? []))
      .catch((err) => active && setError(friendlyErrorMessage(err, "Scenes could not load.")));
    if (!fixed) {
      void (async () => {
        try {
          const mine = await listMyCharacters({ token: await getApiToken() });
          if (active) setCharacters(mine.filter((c) => c.kind !== "described" && c.reference_count > 0));
        } catch (err) {
          if (active) setError(friendlyErrorMessage(err, "Your characters could not load."));
        }
      })();
    }
    return () => {
      active = false;
    };
  }, [fixed, getApiToken, live]);

  React.useEffect(() => {
    if (!run || run.state === 1 || run.state === -1) return undefined;
    const timer = setTimeout(async () => {
      const jid = encodeURIComponent(run.job_id);
      setRun(await apiRequest<SceneRun>(`/scenes/runs/${jid}`, { options: { token: await getApiToken() } }));
    }, 5000);
    return () => clearTimeout(timer);
  }, [getApiToken, run]);

  if (!live) return null;

  async function onPick(next: SceneOption) {
    setScene(next);
    setError("");
    try {
      const sid = encodeURIComponent(next.id);
      const quote = await apiRequest<{ ai_video_credits: number }>(`/scenes/${sid}/quote`, { method: "POST" });
      setCredits(quote.ai_video_credits);
    } catch (err) {
      setError(friendlyErrorMessage(err, "This scene is not available right now."));
    }
  }

  async function onMake() {
    if (!scene || credits === null) return;
    try {
      const token = await getApiToken();
      const sid = encodeURIComponent(scene.id);
      const started = await apiRequest<{ job_id: string }>(`/scenes/${sid}/runs`, {
        method: "POST",
        body: { character_id: characterId, script, product_key: productKey, quoted_credits: credits },
        options: { token },
      });
      setRun({ job_id: started.job_id, state: 4, video_url: "", error: "", refunded: false });
    } catch (err) {
      setError(friendlyErrorMessage(err, "This scene could not start."));
    }
  }

  return (
    <section aria-labelledby="scenes-title" className="space-y-3">
      <h2 id="scenes-title" className="text-lg font-semibold">Scenes</h2>
      {!fixed ? (
        <label className="block text-sm">
          Who is in it?
          <select className="mt-1 block rounded border border-border bg-background px-2 py-1" value={characterId}
            onChange={(e) => setCharacterId(e.target.value)}>
            <option value="">Pick yourself or an original character</option>
            {characters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {scenes.map((option) => (
          <Button key={option.id} variant={scene?.id === option.id ? "default" : "outline"} onClick={() => void onPick(option)}>
            {option.name}
          </Button>
        ))}
      </div>
      {scene ? (
        <div className="space-y-2">
          <label className="block text-sm" htmlFor="scene-script">What should they say?</label>
          <textarea id="scene-script" className="w-full rounded-lg border border-border bg-background p-2" maxLength={900}
            value={script} onChange={(e) => setScript(e.target.value)} />
          {scene.needs_product ? (
            <label className="block text-sm">
              Product photo
              <input className="mt-1 block" type="file" accept="image/*" onChange={async (e) => {
                const file = e.target.files?.[0];
                if (file) setProductKey((await presignAndUpload(file, { token: await getApiToken() })).key);
              }} />
            </label>
          ) : null}
          {credits !== null ? (
            <Button disabled={!script.trim() || !characterId} onClick={() => void onMake()}>{`Make it: ${credits} AI-video credits`}</Button>
          ) : null}
        </div>
      ) : null}
      {run?.state === 1 ? <video className="aspect-[9/16] w-full max-w-xs rounded-xl" src={run.video_url} controls playsInline /> : null}
      {run?.state === -1 ? <p role="alert">{run.error}{run.refunded ? " Your credits are back." : ""}</p> : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
