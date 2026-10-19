"use client";

import * as React from "react";
import Link from "next/link";
import { latestDrop, type PresetDrop } from "./api";

export interface NewThisWeekProps {
  /** Injected in tests; fetched on mount otherwise. */
  readonly initialDrop?: PresetDrop;
}

/** "New this week": the latest released preset drop. Renders nothing until a drop exists. */
export function NewThisWeek({ initialDrop }: NewThisWeekProps) {
  const [drop, setDrop] = React.useState<PresetDrop | null>(initialDrop ?? null);

  React.useEffect(() => {
    if (initialDrop) return;
    let live = true;
    latestDrop()
      .then((next) => live && setDrop(next))
      .catch(() => live && setDrop(null));
    return () => {
      live = false;
    };
  }, [initialDrop]);

  if (!drop || !drop.week || drop.presets.length === 0) return null;
  return (
    <section className="mb-10" aria-label="New this week">
      <h2 className="mb-3 text-lg font-semibold">New this week</h2>
      <ul className="flex gap-3 overflow-x-auto pb-2">
        {drop.presets.map((tile) => (
          <li key={tile.id} className="w-36 shrink-0">
            <Link href={tile.create_url} className="block overflow-hidden rounded-2xl border border-border bg-card"
              data-drop-preset={tile.id}>
              <video className="aspect-[9/16] w-full object-cover" src={tile.preview.loop_url}
                poster={tile.preview.poster_url} autoPlay muted loop playsInline preload="metadata"
                aria-label={`${tile.name} preview`} />
              <span className="block px-3 pb-3 pt-2 text-sm font-semibold">{tile.name}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
