"use client";

import * as React from "react";
import { Link2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** One field: paste a post link, Menivor finds it and reads its numbers. */
export function PasteLink({
  onSubmit,
  autoFocus = false,
}: Readonly<{ onSubmit: (url: string) => Promise<void>; autoFocus?: boolean }>) {
  const [url, setUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!url.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await onSubmit(url.trim());
      setUrl("");
    } catch (err) {
      setError(friendlyErrorMessage(err, "That link could not be added. Try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="w-full">
      <label htmlFor="results-post-link" className="sr-only">
        Post link
      </label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Link2
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            id="results-post-link"
            type="url"
            inputMode="url"
            autoFocus={autoFocus}
            placeholder="Paste a post link"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="neu-inset h-11 pl-9"
            maxLength={2048}
          />
        </div>
        <Button type="submit" size="lg" disabled={busy || !url.trim()}>
          {busy ? "Adding..." : "Add"}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}
