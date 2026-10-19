"use client";

import * as React from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { signInHref } from "@/lib/auth-redirect";
import { useSignedInState } from "@/lib/auth-state";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { listOwnFinishedReels, publishToGallery, type OwnReel } from "./api";

/** Opt in: pick one of your finished reels and show it in the gallery. Nothing is shown until you press Show. */
export function PublishPicker() {
  const { isLoaded, isSignedIn } = useSignedInState();
  const getApiToken = useApiToken();
  const [reels, setReels] = React.useState<readonly OwnReel[] | null>(null);
  const [titles, setTitles] = React.useState<Record<string, string>>({});
  const [shown, setShown] = React.useState<Record<string, string>>({});
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!isSignedIn) return;
    let live = true;
    (async () => {
      try {
        const token = await getApiToken();
        const next = await listOwnFinishedReels({ token });
        if (live) setReels(next);
      } catch (err) {
        if (live) setError(friendlyErrorMessage(err, "Your reels could not load."));
      }
    })();
    return () => {
      live = false;
    };
  }, [getApiToken, isSignedIn]);

  async function show(reel: OwnReel) {
    setError("");
    try {
      const token = await getApiToken();
      const item = await publishToGallery({ job_id: reel.job_id, title: titles[reel.job_id] ?? reel.title ?? "" }, { token });
      setShown((prev) => ({ ...prev, [reel.job_id]: item.id }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "This reel could not be shown."));
    }
  }

  if (isLoaded && !isSignedIn) {
    return (
      <Button asChild>
        <Link href={signInHref("/gallery?publish=1")}>Sign in to show one of your reels</Link>
      </Button>
    );
  }
  if (reels === null) return error ? <p role="alert">{error}</p> : <p className="text-sm text-muted-foreground">Loading your reels</p>;
  if (reels.length === 0) return <p className="text-sm text-muted-foreground">Finish a reel first, then show it here.</p>;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Only what you pick is shown. Your script, links and uploads stay private; others can recreate the look with their own topic.
      </p>
      <ul className="space-y-3" aria-label="Your finished reels">
        {reels.map((reel) => (
          <li key={reel.job_id} className="flex items-center gap-3 rounded-xl border border-border p-3">
            {reel.poster_url ? <img src={reel.poster_url} alt="" className="h-16 w-9 rounded object-cover" /> : null}
            <input
              aria-label="Title"
              className="min-w-0 flex-1 rounded-lg border border-border bg-background px-2 py-1 text-sm"
              maxLength={80}
              value={titles[reel.job_id] ?? reel.title ?? ""}
              onChange={(e) => setTitles((prev) => ({ ...prev, [reel.job_id]: e.target.value }))}
            />
            {shown[reel.job_id] ? (
              <span className="text-sm">Shown</span>
            ) : (
              <Button size="sm" onClick={() => show(reel)}>Show</Button>
            )}
          </li>
        ))}
      </ul>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
