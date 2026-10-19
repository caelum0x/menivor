"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { AlertTriangle, Wallet } from "lucide-react";

import { ApiError } from "@/lib/api";
import {
  formatUsdMicros,
  listGenerationProfiles,
  requestGenerationQuote,
  type GenerationProfile,
  type GenerationQuote,
} from "@/lib/marketplace";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface ProfilePickerProps {
  /** Currently selected profile slug, or null for the classic credit path. */
  value: string | null;
  /** Called with the selected slug + signed quote (or nulls to clear). */
  onChange: (profileId: string | null, quote: GenerationQuote | null) => void;
}

/**
 * Optional pay-as-you-go control for the reel wizard: pick a generation profile,
 * fetch a fresh server-signed quote, and hand both to the wizard so the job is
 * funded from the USD wallet. Never computes price locally — the server quote is
 * authoritative. Selecting "Use credits" clears the wallet path.
 */
export function ProfilePicker({ value, onChange }: ProfilePickerProps) {
  const { getToken, isLoaded } = useAuth();
  const [profiles, setProfiles] = React.useState<GenerationProfile[]>([]);
  const [quote, setQuote] = React.useState<GenerationQuote | null>(null);
  const [error, setError] = React.useState<string>("");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!isLoaded) return;
    let active = true;
    void (async () => {
      try {
        const token = (await getToken()) ?? undefined;
        const rows = await listGenerationProfiles({ token });
        if (active) setProfiles(rows);
      } catch {
        // A missing catalog simply hides the pay-as-you-go control.
        if (active) setProfiles([]);
      }
    })();
    return () => {
      active = false;
    };
  }, [isLoaded, getToken]);

  const select = React.useCallback(
    async (slug: string) => {
      setError("");
      if (!slug) {
        setQuote(null);
        onChange(null, null);
        return;
      }
      setBusy(true);
      try {
        const token = (await getToken()) ?? undefined;
        const fresh = await requestGenerationQuote({ profile: slug }, { token });
        setQuote(fresh);
        onChange(slug, fresh);
      } catch (err) {
        setQuote(null);
        onChange(null, null);
        setError(
          friendlyErrorMessage(err, "Could not price that profile."),
        );
      } finally {
        setBusy(false);
      }
    },
    [getToken, onChange],
  );

  if (profiles.length === 0) return null;

  return (
    <div className="border-t border-border pt-4">
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <Wallet className="h-4 w-4 text-primary" aria-hidden /> Pay-as-you-go
        <span className="font-normal text-muted-foreground">(optional)</span>
      </h3>
      <p className="mb-2 text-xs text-muted-foreground">
        Fund this reel from your USD wallet at a fixed, quoted max cost instead of
        credits.
      </p>
      <select
        value={value ?? ""}
        onChange={(e) => void select(e.target.value)}
        disabled={busy}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
        aria-label="Generation profile"
      >
        <option value="">Use credits (classic)</option>
        {profiles.map((p) => (
          <option key={p.slug} value={p.slug}>
            {p.display_name}
          </option>
        ))}
      </select>

      {error && (
        <p className="mt-2 flex items-center gap-1 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden /> {error}
        </p>
      )}

      {value && quote && (
        <div className="mt-3 rounded-md border bg-muted/40 px-3 py-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Max cost</span>
            <span className="tabular-nums font-medium">
              {formatUsdMicros(quote.max_cost_micros)}
            </span>
          </div>
          {!quote.within_budget && quote.cap_micros != null && (
            <p className="mt-1 text-xs text-destructive">
              Above your {formatUsdMicros(quote.cap_micros)} cap.
            </p>
          )}
          <p className="mt-1 text-xs text-muted-foreground">
            Reserved from your wallet on create; the unused remainder is released.
          </p>
        </div>
      )}
    </div>
  );
}
