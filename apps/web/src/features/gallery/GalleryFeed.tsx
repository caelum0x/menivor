"use client";

import * as React from "react";
import Link from "next/link";
import { listGallery, type GalleryItem } from "./api";

export interface GalleryFeedProps {
  readonly initialItems?: readonly GalleryItem[];
}

/** Opt-in finished reels. Each one says it is AI-generated and can be recreated with your own topic. */
export function GalleryFeed({ initialItems }: GalleryFeedProps) {
  const [items, setItems] = React.useState<readonly GalleryItem[] | null>(initialItems ?? null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    if (initialItems) return;
    let live = true;
    listGallery()
      .then((next) => live && setItems(next))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [initialItems]);

  if (failed) return <p role="alert" className="text-sm text-muted-foreground">The gallery could not load. Try again in a moment.</p>;
  if (items === null) return <p className="text-sm text-muted-foreground">Loading the gallery</p>;
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Nothing here yet. <Link className="underline underline-offset-4" href="/gallery?publish=1">Show one of your reels</Link>.
      </p>
    );
  }
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" aria-label="Gallery">
      {items.map((item) => (
        <li key={item.id} className="overflow-hidden rounded-2xl border border-border bg-card">
          <video
            className="aspect-[9/16] w-full object-cover"
            src={item.preview_url}
            poster={item.poster_url}
            autoPlay
            muted
            loop
            playsInline
            preload="metadata"
            aria-label={`${item.title || "Gallery reel"} preview`}
          />
          <div className="space-y-1 px-3 pb-3 pt-2">
            <p className="text-sm font-semibold">{item.title || "Untitled reel"}</p>
            {item.preset_name ? <p className="text-xs text-muted-foreground">{item.preset_name} preset</p> : null}
            <p className="text-xs text-muted-foreground" data-testid="provenance">
              {item.provenance.ai_generated ? "AI-generated" : "Made"} with {item.provenance.generator}.{" "}
              <a className="underline underline-offset-2" href={item.provenance.report_url}>Report</a>
            </p>
            <Link className="block text-sm font-medium underline underline-offset-4" href={item.recreate_url}>
              Recreate{item.remix_count > 0 ? ` (${item.remix_count})` : ""}
            </Link>
          </div>
        </li>
      ))}
    </ul>
  );
}
