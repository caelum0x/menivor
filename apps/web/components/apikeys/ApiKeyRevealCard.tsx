"use client";

import * as React from "react";
import { KeyRound, ShieldAlert, X } from "lucide-react";
import type { CreatedApiKey } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { CopyBox } from "@/components/apikeys/CopyBox";

interface ApiKeyRevealCardProps {
  /** The freshly minted key, including its one-time raw secret. */
  created: CreatedApiKey;
  /** Dismiss the reveal (the caller has copied/stored the key). */
  onDismiss: () => void;
}

/**
 * The ONE-TIME reveal of a newly minted API key. Shows the full raw secret in a
 * copy box with a prominent "you won't see it again" warning. The raw key exists
 * only in this component's props (never persisted client-side) and is gone once
 * dismissed.
 */
export function ApiKeyRevealCard({ created, onDismiss }: ApiKeyRevealCardProps) {
  return (
    <Card className="border-primary/40 bg-primary/5">
      <CardContent className="space-y-4 p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
              <KeyRound className="size-4" aria-hidden />
            </span>
            <div>
              <p className="font-semibold">API key created</p>
              <p className="text-sm text-muted-foreground">
                Key <span className="font-medium">{created.name}</span> is ready.
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onDismiss}
            aria-label="Dismiss"
          >
            <X className="size-4" aria-hidden /> Done
          </Button>
        </div>

        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
        >
          <ShieldAlert
            className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400"
            aria-hidden
          />
          <p>
            Copy and store this key now — you won&apos;t be able to see it again.
            We only keep a hash, so it can&apos;t be recovered. If you lose it,
            revoke it and create a new one.
          </p>
        </div>

        <CopyBox value={created.key} label="Copy API key" />
      </CardContent>
    </Card>
  );
}
