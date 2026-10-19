"use client";

/**
 * Section 2: pain-point thread finder. A search box (global or scoped to
 * specific subreddits) against Reddit's public, read-only search, with a
 * drafted reply per thread. There is no "post" button anywhere in this
 * component — see `app.domains.launch_kit.service`'s module docstring:
 * there is no code path server-side that calls Reddit's comment/vote APIs.
 */

import * as React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  listPainPointDrafts,
  searchPainPoints,
  setPainPointDraftStatus,
  type PainPointDraft,
} from "./api";
import { sortDrafts } from "./view-model";
import { PainPointDraftRow } from "./PainPointDraftRow";

interface Props {
  readonly productName: string;
}

export function PainPointFinder({ productName }: Props) {
  const getApiToken = useApiToken();
  const [query, setQuery] = React.useState("");
  const [subreddits, setSubreddits] = React.useState("");
  const [drafts, setDrafts] = React.useState<readonly PainPointDraft[]>([]);
  const [note, setNote] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [loaded, setLoaded] = React.useState(false);

  const refreshDrafts = React.useCallback(async () => {
    const token = await getApiToken();
    const { drafts: rows } = await listPainPointDrafts({ productName: productName || undefined }, { token });
    setDrafts(rows);
  }, [getApiToken, productName]);

  React.useEffect(() => {
    if (loaded) return;
    setLoaded(true);
    refreshDrafts().catch(() => {});
  }, [loaded, refreshDrafts]);

  const search = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy || !query.trim()) return;
    setBusy(true);
    setError("");
    try {
      const token = await getApiToken();
      const list = subreddits
        .split(",")
        .map((s) => s.trim().replace(/^r\//i, ""))
        .filter(Boolean);
      const result = await searchPainPoints(
        { query, subreddits: list, productName: productName || undefined },
        { token },
      );
      setNote(result.note);
      await refreshDrafts();
    } catch (err) {
      setError(friendlyErrorMessage(err, "That search could not be completed."));
    } finally {
      setBusy(false);
    }
  };

  const approve = async (id: string) => {
    const token = await getApiToken();
    const updated = await setPainPointDraftStatus(id, "approved", { token });
    setDrafts((current) => current.map((d) => (d.id === id ? updated : d)));
  };

  const dismiss = async (id: string) => {
    const token = await getApiToken();
    const updated = await setPainPointDraftStatus(id, "dismissed", { token });
    setDrafts((current) => current.map((d) => (d.id === id ? updated : d)));
  };

  const ordered = sortDrafts(drafts);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Pain-point thread finder</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Search Reddit (global or a few subreddits) for people describing the problem this product solves.
          Every result gets a drafted reply for you to review — approve or dismiss here, then copy it to Reddit
          yourself. Nothing is ever posted automatically.
        </p>
        <form onSubmit={(e) => void search(e)} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
          <Input
            aria-label="Search query"
            placeholder="e.g. onboarding drop-off"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Input
            aria-label="Subreddits (optional, comma-separated)"
            placeholder="subreddits, comma-separated (optional)"
            value={subreddits}
            onChange={(e) => setSubreddits(e.target.value)}
          />
          <Button type="submit" disabled={busy || !query.trim()}>
            {busy ? "Searching..." : "Search"}
          </Button>
        </form>
        {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}

        {ordered.length > 0 ? (
          <ul className="divide-y divide-border" data-testid="pain-point-drafts">
            {ordered.map((draft) => (
              <PainPointDraftRow key={draft.id} draft={draft} onApprove={approve} onDismiss={dismiss} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No drafts yet. Search above to find threads.</p>
        )}
      </CardContent>
    </Card>
  );
}
