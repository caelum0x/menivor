"use client";

import * as React from "react";
import Link from "next/link";
import { searchTitles, type SearchHit } from "./api";

export const DEBOUNCE_MS = 250;

/** Search this channel as you type. */
export function SearchBox({ handle }: Readonly<{ handle: string }>) {
  const [q, setQ] = React.useState("");
  const [hits, setHits] = React.useState<readonly SearchHit[]>([]);

  React.useEffect(() => {
    if (q.trim().length < 2) {
      setHits([]);
      return undefined;
    }
    let live = true;
    const timer = setTimeout(() => {
      void searchTitles(q, handle).then((list) => live && setHits(list));
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [q, handle]);

  return (
    <section aria-label="Search this channel" className="mb-6">
      <label className="text-sm">
        <span className="sr-only">Search this channel</span>
        <input className="w-full rounded-lg border px-3 py-2" type="search" placeholder="Search this channel" value={q}
          onChange={(e) => setQ(e.target.value)} />
      </label>
      {hits.length ? (
        <ul className="mt-2 space-y-1 text-sm">
          {hits.map((hit) => (
            <li key={hit.id}>
              <Link className="underline" href={`/c/${encodeURIComponent(hit.channel)}/${encodeURIComponent(hit.id)}`}>{hit.title}</Link>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
