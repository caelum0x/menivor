"use client";

import * as React from "react";
import { clock, publicChapters, type Chapter } from "./api";

/** Chapters under the player (from the AI panel); renders nothing when a title has none. */
export function Chapters({ titleId }: Readonly<{ titleId: string }>) {
  const [chapters, setChapters] = React.useState<readonly Chapter[]>([]);
  React.useEffect(() => {
    let live = true;
    void publicChapters(titleId).then((list) => live && setChapters(list));
    return () => {
      live = false;
    };
  }, [titleId]);
  if (!chapters.length) return null;
  return (
    <section aria-label="Chapters" className="mt-4 text-sm">
      <h2 className="mb-1 font-semibold">Chapters</h2>
      <ol className="space-y-1">
        {chapters.map((c) => <li key={c.start_s}><span className="tabular-nums">{clock(c.start_s)}</span> {c.title}</li>)}
      </ol>
    </section>
  );
}
