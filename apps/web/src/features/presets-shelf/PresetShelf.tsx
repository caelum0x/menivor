"use client";

import * as React from "react";
import Link from "next/link";
import { listShelf, type PresetTile } from "./api";

export interface PresetShelfProps {
  /** Injected in tests and on the server; fetched on mount otherwise. */
  readonly initialTiles?: readonly PresetTile[];
}

/** The public preset shelf: moving preview loops, one tap into Create. */
export function PresetShelf({ initialTiles }: PresetShelfProps) {
  const [tiles, setTiles] = React.useState<readonly PresetTile[] | null>(initialTiles ?? null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    if (initialTiles) return;
    let live = true;
    listShelf()
      .then((next) => live && setTiles(next))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [initialTiles]);

  if (failed) {
    return <p role="alert" className="text-sm text-muted-foreground">The presets could not load. Try again in a moment.</p>;
  }
  if (tiles === null) {
    return <p className="text-sm text-muted-foreground">Loading presets</p>;
  }
  if (tiles.length === 0) {
    return <p className="text-sm text-muted-foreground">New presets are on the way.</p>;
  }
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" aria-label="Presets">
      {tiles.map((tile) => (
        <li key={tile.id}>
          <Link
            href={tile.create_url}
            className="group block overflow-hidden rounded-2xl border border-border bg-card"
            data-preset={tile.id}
          >
            <video
              className="aspect-[9/16] w-full object-cover"
              src={tile.preview.loop_url}
              poster={tile.preview.poster_url}
              autoPlay
              muted
              loop
              playsInline
              preload="metadata"
              aria-label={`${tile.name} preview`}
            />
            <span className="block px-3 pb-3 pt-2">
              <span className="block text-sm font-semibold">{tile.name}</span>
              <span className="block text-xs text-muted-foreground">{tile.credit_label}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
