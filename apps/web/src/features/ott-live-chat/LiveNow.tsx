"use client";

import * as React from "react";
import Link from "next/link";
import { liveNow, type LiveSummary } from "./api";

/** "Live now" on a channel page: renders nothing when nobody is live. */
export function LiveNow({ handle }: Readonly<{ handle: string }>) {
  const [streams, setStreams] = React.useState<readonly LiveSummary[]>([]);
  React.useEffect(() => {
    let active = true;
    void liveNow(handle).then((list) => active && setStreams(list));
    return () => {
      active = false;
    };
  }, [handle]);
  if (!streams.length) return null;
  return (
    <section aria-label="Live now" className="mb-6">
      <h2 className="mb-2 text-lg font-semibold">Live now</h2>
      <ul className="space-y-1">
        {streams.map((s) => (
          <li key={s.id}>
            <Link className="underline" href={`/c/${encodeURIComponent(handle)}/live/${encodeURIComponent(s.id)}`}>{s.title}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
