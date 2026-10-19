"use client";

/**
 * Section 3: competitor backlinks. Shows the free directory-fallback result
 * by default. If DataForSEO is not configured on the server, this shows an
 * honest "connect DataForSEO for live data" state — never a fake "no
 * results" that reads like a dead feature. Live data only ever runs when a
 * key is configured on the server AND the caller explicitly opts in.
 */

import * as React from "react";
import { ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { findCompetitorBacklinks, type BacklinksResult } from "./api";
import { backlinksState, domainLooksValid } from "./view-model";

export function CompetitorBacklinks() {
  const getApiToken = useApiToken();
  const [domain, setDomain] = React.useState("");
  const [result, setResult] = React.useState<BacklinksResult | null>(null);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const lookup = async (event: React.FormEvent, allowLive: boolean) => {
    event.preventDefault();
    if (busy || !domainLooksValid(domain)) return;
    setBusy(true);
    setError("");
    try {
      const token = await getApiToken();
      setResult(await findCompetitorBacklinks(domain, allowLive, { token }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "Backlinks could not be looked up."));
    } finally {
      setBusy(false);
    }
  };

  const state = result ? backlinksState(result) : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Competitor backlinks</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Find where a competitor is listed or linked, so you submit to the same places.
        </p>
        <form onSubmit={(e) => void lookup(e, false)} className="flex gap-2">
          <Input
            aria-label="Competitor domain"
            placeholder="competitor.com"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
          />
          <Button type="submit" disabled={busy || !domainLooksValid(domain)}>
            {busy ? "Looking up..." : "Look up"}
          </Button>
        </form>
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}

        {state === "not_configured" ? (
          <div className="rounded-md border border-white/10 bg-white/[0.03] p-4 text-sm" data-testid="backlinks-not-configured">
            <p className="font-medium">Connect DataForSEO for live backlink data</p>
            <p className="mt-1 text-muted-foreground">{result?.message}</p>
          </div>
        ) : null}

        {state === "configured_not_live" ? (
          <div className="space-y-2" data-testid="backlinks-configured-not-live">
            <p className="text-sm text-muted-foreground">{result?.message}</p>
            <Button size="sm" variant="outline" disabled={busy} onClick={(e) => void lookup(e, true)}>
              Fetch live data (spends credits)
            </Button>
          </div>
        ) : null}

        {state === "live_data" && result ? (
          <ul className="divide-y divide-border" data-testid="backlinks-live">
            {result.backlinks.map((link, index) => (
              <li key={`${link.source_domain}-${index}`} className="flex items-center justify-between gap-3 py-2">
                <a
                  href={link.target_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 hover:underline"
                >
                  {link.source_domain} <ExternalLink className="size-3" aria-hidden />
                </a>
                {link.rank !== null ? <span className="text-sm text-muted-foreground">rank {link.rank}</span> : null}
              </li>
            ))}
            {result.backlinks.length === 0 ? (
              <li className="py-2 text-sm text-muted-foreground">No live backlinks found for this domain.</li>
            ) : null}
          </ul>
        ) : null}

        {result && result.fallback_directories.length > 0 ? (
          <div>
            <p className="mb-2 text-sm font-medium">General launch directories to try meanwhile</p>
            <ul className="flex flex-wrap gap-2">
              {result.fallback_directories.map((directory) => (
                <li key={directory.id}>
                  <a
                    href={directory.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded-full border border-white/10 px-3 py-1 text-xs hover:underline"
                  >
                    {directory.name} <ExternalLink className="size-3" aria-hidden />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
