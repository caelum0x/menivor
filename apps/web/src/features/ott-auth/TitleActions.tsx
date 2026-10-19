"use client";

import * as React from "react";
import { getRating, myList, rateTitle, setOnList, unrateTitle, type Rating } from "./api";
import { readSession } from "./session-store";

/** My list and stars for one title (Wave Q QM1.5). Shown only to a viewer signed in to this channel. */
export function TitleActions({ handle, titleId }: Readonly<{ handle: string; titleId: string }>) {
  const [session, setSession] = React.useState<string | null>(null);
  const [onList, setList] = React.useState(false);
  const [rating, setRating] = React.useState<Rating | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    const stored = readSession(handle);
    if (!stored) return;
    setSession(stored.session);
    void myList(handle, stored.session).then((r) => setList(r.items.some((i) => i.id === titleId))).catch(() => undefined);
    void getRating(handle, stored.session, titleId).then(setRating).catch(() => undefined);
  }, [handle, titleId]);

  if (!session) return null;
  const toggle = async () => {
    try {
      await setOnList(handle, session, titleId, !onList);
      setList(!onList);
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not save.");
    }
  };
  const rate = async (stars: number) => {
    try {
      // The same star again takes the rating back.
      setRating(rating?.mine === stars ? await unrateTitle(handle, session, titleId)
        : await rateTitle(handle, session, titleId, stars));
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not save.");
    }
  };

  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
      <button type="button" className="rounded-lg border px-3 py-1" aria-pressed={onList} onClick={() => void toggle()}>
        {onList ? "On my list" : "Save to my list"}
      </button>
      <span role="group" aria-label="Rate this title" className="flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" aria-label={`${n} of 5`} aria-pressed={rating?.mine === n}
            className={`h-7 w-7 rounded border ${rating?.mine && n <= rating.mine ? "bg-foreground text-background" : ""}`}
            onClick={() => void rate(n)}>{n}</button>
        ))}
      </span>
      {rating && rating.count > 0 ? (
        <span className="text-muted-foreground">{rating.average?.toFixed(1)} from {rating.count}</span>
      ) : null}
      {error ? <p role="alert" className="w-full">{error}</p> : null}
    </div>
  );
}
