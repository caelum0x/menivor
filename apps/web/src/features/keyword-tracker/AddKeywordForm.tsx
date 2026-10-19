"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface ConnectedApp {
  readonly id: string;
  readonly name: string;
}

interface Props {
  readonly disabled: boolean;
  /** Apps from a connected App Store Connect account (Phase 3 "Connect your store"),
   * so a creator can pick one instead of typing its numeric id by hand. */
  readonly connectedApps: readonly ConnectedApp[];
  readonly onSubmit: (input: { appId: string; term: string; appName: string; country: string }) => Promise<void>;
}

const CUSTOM = "__custom__";

/** App Store numeric id + a keyword + an optional country. One keyword per submit. */
export function AddKeywordForm({ disabled, connectedApps, onSubmit }: Props) {
  const [picked, setPicked] = React.useState<string>(connectedApps[0]?.id ?? CUSTOM);
  const [appId, setAppId] = React.useState("");
  const [appName, setAppName] = React.useState("");
  const [term, setTerm] = React.useState("");
  const [country, setCountry] = React.useState("us");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const usingCustom = picked === CUSTOM || connectedApps.length === 0;
  const resolvedApp = usingCustom ? { id: appId.trim(), name: appName.trim() }
    : connectedApps.find((a) => a.id === picked) ?? null;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy || disabled || !resolvedApp?.id || !term.trim()) return;
    setBusy(true);
    setError("");
    try {
      await onSubmit({ appId: resolvedApp.id, term: term.trim(), appName: resolvedApp.name, country });
      setTerm("");
    } catch (err) {
      setError(friendlyErrorMessage(err, "That keyword could not be added."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-2">
      {connectedApps.length > 0 ? (
        <Select
          aria-label="Which app"
          value={picked}
          onChange={(e) => setPicked(e.target.value)}
          disabled={disabled}
        >
          {connectedApps.map((app) => (
            <option key={app.id} value={app.id}>
              {app.name || app.id}
            </option>
          ))}
          <option value={CUSTOM}>Another app (enter its App Store id)...</option>
        </Select>
      ) : null}
      <div className="grid gap-2 sm:grid-cols-[1fr_1fr_90px_auto]">
        {usingCustom ? (
          <Input
            aria-label="App Store numeric id"
            placeholder="App Store id (e.g. 6780166477)"
            value={appId}
            onChange={(e) => setAppId(e.target.value)}
            disabled={disabled}
          />
        ) : (
          <Input aria-label="App" value={resolvedApp?.name || resolvedApp?.id || ""} disabled readOnly />
        )}
        <Input
          aria-label="Keyword to track"
          placeholder="Keyword (e.g. calorie tracker)"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          disabled={disabled}
        />
        <Input
          aria-label="Store country code"
          placeholder="us"
          value={country}
          maxLength={2}
          onChange={(e) => setCountry(e.target.value.toLowerCase())}
          disabled={disabled}
        />
        <Button type="submit" disabled={disabled || busy || !resolvedApp?.id || !term.trim()}>
          {busy ? "Adding..." : "Track"}
        </Button>
      </div>
      {usingCustom ? (
        <Input
          aria-label="App name (optional, for display only)"
          placeholder="App name (optional)"
          value={appName}
          onChange={(e) => setAppName(e.target.value)}
          disabled={disabled}
        />
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}
