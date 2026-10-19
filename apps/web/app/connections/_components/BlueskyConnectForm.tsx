"use client";

import * as React from "react";
import { Loader2, Plug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface BlueskyConnectFormProps {
  busy: boolean;
  onSubmit: (handle: string, appPassword: string, pds: string) => void;
}

/**
 * Bluesky connects with the handle plus an app password (Settings > Privacy and
 * security > App passwords in Bluesky). The password is sent once to our API,
 * stored encrypted, and only ever used against the account's own server.
 */
export function BlueskyConnectForm({ busy, onSubmit }: Readonly<BlueskyConnectFormProps>) {
  const handleId = React.useId();
  const passwordId = React.useId();
  const pdsId = React.useId();
  const [handle, setHandle] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [pds, setPds] = React.useState("");
  const [showAdvanced, setShowAdvanced] = React.useState(false);

  const canSubmit = handle.trim().length >= 3 && password.trim().length >= 8 && !busy;

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) onSubmit(handle.trim(), password.trim(), pds.trim());
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor={handleId}>Handle</Label>
        <Input
          id={handleId}
          autoComplete="username"
          placeholder="you.bsky.social"
          value={handle}
          disabled={busy}
          onChange={(e) => setHandle(e.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={passwordId}>App password</Label>
        <Input
          id={passwordId}
          type="password"
          autoComplete="off"
          placeholder="xxxx-xxxx-xxxx-xxxx"
          value={password}
          disabled={busy}
          onChange={(e) => setPassword(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Create one in Bluesky under Settings, Privacy and security, App passwords. Do not use
          your main password.
        </p>
      </div>
      {showAdvanced ? (
        <div className="space-y-1.5">
          <Label htmlFor={pdsId}>Hosting provider (optional)</Label>
          <Input
            id={pdsId}
            placeholder="https://bsky.social"
            value={pds}
            disabled={busy}
            onChange={(e) => setPds(e.target.value)}
          />
        </div>
      ) : (
        <button
          type="button"
          className="text-xs text-muted-foreground underline-offset-4 hover:underline"
          onClick={() => setShowAdvanced(true)}
        >
          Self-hosted account?
        </button>
      )}
      <Button type="submit" size="sm" className="w-full" disabled={!canSubmit}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Plug className="size-4" aria-hidden />}
        Connect Bluesky
      </Button>
    </form>
  );
}
