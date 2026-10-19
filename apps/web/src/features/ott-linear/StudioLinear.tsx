"use client";

import * as React from "react";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { guideUrl, listLinear, saveLinear, type LinearView } from "./api";

/** A Always-on channel from my free titles: tick titles in order, choose ad breaks, save. */
export function StudioLinear({ titles }: Readonly<{ titles: readonly { id: string; title: string; access_tier: string; status: string }[] }>) {
  const getApiToken = useApiToken();
  const free = titles.filter((t) => t.access_tier === "free" && t.status === "published");
  const [picked, setPicked] = React.useState<string[]>([]);
  const [every, setEvery] = React.useState(3);
  const [saved, setSaved] = React.useState<LinearView | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    void (async () => {
      try {
        const first = (await listLinear({ token: await getApiToken() })).linear[0];
        if (first) {
          setSaved(first);
          setPicked([...first.title_ids]);
          setEvery(first.ad_break_every);
        }
      } catch {
        // a first-time creator has none yet
      }
    })();
  }, [getApiToken]);

  const toggle = (id: string) => setPicked((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
  const save = async () => {
    try {
      setSaved(await saveLinear({ title_ids: picked, ad_break_every: every }, { token: await getApiToken() }));
      setError("");
    } catch (err) {
      setError(friendlyErrorMessage(err, "The channel could not be saved."));
    }
  };

  return (
    <section aria-label="Always-on channel" className="space-y-2 rounded-xl border border-border p-3 text-sm">
      <h2 className="font-semibold">Always-on channel</h2>
      <ul className="space-y-1">
        {free.map((t) => (
          <li key={t.id}>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={picked.includes(t.id)} onChange={() => toggle(t.id)} />
              {picked.includes(t.id) ? `${picked.indexOf(t.id) + 1}. ` : ""}{t.title}
            </label>
          </li>
        ))}
      </ul>
      <label>Ad break after every
        <select className="mx-2 rounded border px-1" value={every} onChange={(e) => setEvery(Number(e.target.value))}>
          {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n === 0 ? "never" : n}</option>)}
        </select>
        titles
      </label>
      <button type="button" className="ml-2 rounded-lg border px-3 py-1" disabled={!picked.length} onClick={() => void save()}>
        Save channel
      </button>
      {saved ? (
        <p>Plays at <code>{saved.watch_url}</code>. Program guide: <a className="underline" href={guideUrl(saved.slug)}>XMLTV</a>.</p>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}
