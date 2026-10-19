"use client";

import * as React from "react";
import { AlertCircle, KeyRound, Loader2 } from "lucide-react";
import type { CreatedApiKey } from "@/lib/types";
import { ApiError, createApiKey } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface CreateApiKeyFormProps {
  /** Called with the newly minted key (including its one-time raw secret). */
  onCreated: (key: CreatedApiKey) => void;
}

const NAME_MAX = 200;

type Phase =
  | { status: "idle" }
  | { status: "creating" }
  | { status: "error"; message: string };

/**
 * Form to mint a personal API key: the caller names it, submits, and the parent
 * receives the created key (with its one-time raw secret) to reveal. The name
 * input is a controlled, immutable value and is cleared after a successful mint.
 */
export function CreateApiKeyForm({ onCreated }: CreateApiKeyFormProps) {
  const getApiToken = useApiToken();
  const [name, setName] = React.useState("");
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });

  const busy = phase.status === "creating";
  const canSubmit = !busy && name.trim().length > 0;

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (name.trim().length === 0) return;

      setPhase({ status: "creating" });
      try {
        const token = await getApiToken();
        const created = await createApiKey(name, { token });
        onCreated(created);
        setName("");
        setPhase({ status: "idle" });
      } catch (err) {
        const message =
          friendlyErrorMessage(err, "Could not create your API key. Please try again.");
        setPhase({ status: "error", message });
      }
    },
    [getApiToken, name, onCreated],
  );

  return (
    <Card>
      <CardContent className="p-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="api-key-name">Key name</Label>
            <Input
              id="api-key-name"
              value={name}
              maxLength={NAME_MAX}
              placeholder="e.g. CI, n8n, my laptop"
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
              required
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              A label to help you recognise this key later. You can create
              several and revoke any of them independently.
            </p>
          </div>

          {phase.status === "error" && (
            <p
              role="alert"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              {phase.message}
            </p>
          )}

          <Button type="submit" disabled={!canSubmit} className="w-full">
            {busy ? (
              <>
                <Loader2 className="animate-spin" /> Creating key…
              </>
            ) : (
              <>
                <KeyRound /> Create API key
              </>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
