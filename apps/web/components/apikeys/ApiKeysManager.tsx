"use client";

import * as React from "react";
import { AlertTriangle, KeyRound, RefreshCw } from "lucide-react";
import type { ApiKey, CreatedApiKey } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiKeyCard } from "@/components/apikeys/ApiKeyCard";
import { ApiKeyRevealCard } from "@/components/apikeys/ApiKeyRevealCard";
import { ApiKeyUsageSnippet } from "@/components/apikeys/ApiKeyUsageSnippet";
import { CreateApiKeyForm } from "@/components/apikeys/CreateApiKeyForm";
import { useMyApiKeys } from "@/components/apikeys/use-my-api-keys";

/**
 * The Developer / API Keys page body: a create form + usage snippet on the left
 * and the caller's keys on the right, with loading / error / empty states and
 * revoke. When a key is minted its raw secret is revealed exactly once at the
 * top; dismissing it drops the secret from memory.
 */
export function ApiKeysManager() {
  const { status, keys, errorMessage, reload, prepend, revoke } =
    useMyApiKeys();
  const [revealed, setRevealed] = React.useState<CreatedApiKey | null>(null);

  const handleCreated = React.useCallback(
    (created: CreatedApiKey) => {
      setRevealed(created);
      // Reflect the new key in the list immediately (without the raw secret).
      const listItem: ApiKey = {
        id: created.id,
        name: created.name,
        prefix: created.prefix,
        last_used_at: null,
        revoked: false,
        created_at: created.created_at ?? null,
      };
      prepend(listItem);
    },
    [prepend],
  );

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,380px)_1fr]">
      <div className="space-y-6 lg:sticky lg:top-6 lg:self-start">
        <CreateApiKeyForm onCreated={handleCreated} />
        <ApiKeyUsageSnippet />
      </div>

      <div className="space-y-6">
        {revealed && (
          <ApiKeyRevealCard
            created={revealed}
            onDismiss={() => setRevealed(null)}
          />
        )}

        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold tracking-tight">
            Your API keys
            {status === "ready" && keys.length > 0 && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                {keys.length}
              </span>
            )}
          </h2>
          <Button
            variant="outline"
            size="sm"
            onClick={reload}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={status === "loading" ? "size-4 animate-spin" : "size-4"}
              aria-hidden
            />
            Refresh
          </Button>
        </div>

        {status === "loading" && <ApiKeysSkeleton />}

        {status === "error" && (
          <ErrorPanel message={errorMessage} onRetry={reload} />
        )}

        {status === "ready" && keys.length === 0 && <EmptyState />}

        {status === "ready" && keys.length > 0 && (
          <ul className="grid gap-4 sm:grid-cols-2">
            {keys.map((apiKey) => (
              <li key={apiKey.id}>
                <ApiKeyCard apiKey={apiKey} onRevoke={revoke} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ApiKeysSkeleton() {
  return (
    <ul className="grid gap-4 sm:grid-cols-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <li key={i}>
          <Card>
            <CardContent className="space-y-3 p-5">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-8 w-24 rounded-md" />
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}

function ErrorPanel({
  message,
  onRetry,
}: Readonly<{ message: string; onRetry: () => void }>) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-destructive"
            aria-hidden
          />
          <div>
            <p className="font-medium">Couldn&apos;t load your API keys</p>
            <p className="text-sm text-muted-foreground">{message}</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden /> Try again
        </Button>
      </CardContent>
    </Card>
  );
}

function EmptyState() {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
          <KeyRound className="size-6 text-primary" aria-hidden />
        </span>
        <div>
          <p className="font-medium">No API keys yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Create a key to access the ReelForge REST API programmatically from
            your own scripts, CI, or automation tools.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
