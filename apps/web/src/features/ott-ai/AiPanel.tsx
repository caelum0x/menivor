"use client";

import * as React from "react";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { updateTitle } from "@/src/features/ott-cms/api";
import { getAi, LANGUAGES, runAi, type AiKind, type AiOutput } from "./api";

const KINDS: readonly [AiKind, string][] = [
  ["subtitles", "Subtitles"], ["chapters", "Chapters"], ["metadata", "Title and description ideas"], ["dub", "Dubbed audio"],
];
export const POLL_MS = 5000;

/** Pick a title, choose what to make and the languages, and apply the suggestions you like. */
export function AiPanel({ titles }: Readonly<{ titles: readonly { id: string; title: string }[] }>) {
  const getApiToken = useApiToken();
  const [titleId, setTitleId] = React.useState(titles[0]?.id ?? "");
  const [kinds, setKinds] = React.useState<AiKind[]>(["subtitles", "chapters"]);
  const [source, setSource] = React.useState("en");
  const [languages, setLanguages] = React.useState<string[]>([]);
  const [outputs, setOutputs] = React.useState<readonly AiOutput[]>([]);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!titleId) return undefined;
    let live = true;
    const load = async () => {
      try {
        const data = await getAi(titleId, { token: await getApiToken() });
        if (live) setOutputs(data.outputs);
      } catch {
        // the panel shows nothing until the first run
      }
    };
    void load();
    const timer = setInterval(() => void load(), POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [titleId, getApiToken]);

  const toggle = <T,>(list: T[], item: T) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);
  const run = async () => {
    try {
      setOutputs((await runAi(titleId, { kinds, languages, source_language: source }, { token: await getApiToken() })).outputs);
      setError("");
    } catch (err) {
      setError(friendlyErrorMessage(err, "The AI panel could not start."));
    }
  };
  const suggestion = outputs.find((o) => o.kind === "metadata" && o.status === "done")?.suggestion;
  const chapters = outputs.find((o) => o.kind === "chapters" && o.status === "done")?.chapters ?? [];

  return (
    <section aria-label="AI panel" className="space-y-2 rounded-xl border border-border p-3 text-sm">
      <h2 className="font-semibold">AI panel</h2>
      <label>Title
        <select className="ml-2 rounded border px-1" value={titleId} onChange={(e) => setTitleId(e.target.value)}>
          {titles.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
        </select>
      </label>
      <div className="flex flex-wrap gap-3">
        {KINDS.map(([kind, label]) => (
          <label key={kind} className="flex items-center gap-1">
            <input type="checkbox" checked={kinds.includes(kind)} onChange={() => setKinds((k) => toggle(k, kind))} />{label}
          </label>
        ))}
      </div>
      <label>Spoken language
        <select className="ml-2 rounded border px-1" value={source} onChange={(e) => setSource(e.target.value)}>
          {LANGUAGES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
        </select>
      </label>
      <fieldset className="flex flex-wrap gap-3">
        <legend>Also in</legend>
        {LANGUAGES.filter(([code]) => code !== source).map(([code, name]) => (
          <label key={code} className="flex items-center gap-1">
            <input type="checkbox" checked={languages.includes(code)} onChange={() => setLanguages((l) => toggle(l, code))} />{name}
          </label>
        ))}
      </fieldset>
      <button type="button" className="rounded-lg bg-foreground px-3 py-1 text-background" disabled={!titleId || !kinds.length}
        onClick={() => void run()}>Make them</button>
      <ul>
        {outputs.filter((o) => o.kind !== "transcript").map((o) => (
          <li key={`${o.kind}-${o.language}`}>{o.kind} {o.language}: {o.status}{o.error ? ` (${o.error})` : ""}</li>
        ))}
      </ul>
      {chapters.length ? <p>Chapters: {chapters.map((c) => c.title).join(", ")}</p> : null}
      {suggestion?.title ? (
        <div className="rounded-lg bg-muted p-2">
          <p className="font-semibold">{suggestion.title}</p>
          <p>{suggestion.synopsis}</p>
          <button type="button" className="underline" onClick={async () => {
            await updateTitle(titleId, { title: suggestion.title, synopsis: suggestion.synopsis }, { token: await getApiToken() })
              .catch((err) => setError(friendlyErrorMessage(err, "The title could not be updated.")));
          }}>Use this</button>
        </div>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}
