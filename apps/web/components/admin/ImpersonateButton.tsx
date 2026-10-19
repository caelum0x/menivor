"use client";

import * as React from "react";
import { Check, Copy, Loader2, UserCog } from "lucide-react";
import { ApiError, adminImpersonate } from "@/lib/api";
import type { Impersonation } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface ImpersonateButtonProps {
  /** The target user to mint an impersonation grant for. */
  userId: string;
  /** Label for accessibility (e.g. the user's email). */
  label?: string;
}

/**
 * Mints a short-lived, audited impersonation token for a user
 * (POST /admin/impersonate, staff-only). The minted token is shown once with a
 * copy affordance and never persisted. Writing an `admin.impersonated` audit row
 * is handled server-side.
 */
export function ImpersonateButton({ userId, label }: Readonly<ImpersonateButtonProps>) {
  const getApiToken = useApiToken();
  const [pending, setPending] = React.useState(false);
  const [grant, setGrant] = React.useState<Impersonation | null>(null);
  const [error, setError] = React.useState("");
  const [copied, setCopied] = React.useState(false);

  const onImpersonate = React.useCallback(async () => {
    setPending(true);
    setError("");
    setGrant(null);
    try {
      const token = await getApiToken();
      const result = await adminImpersonate(userId, { token });
      setGrant(result);
    } catch (err) {
      setError(
        friendlyErrorMessage(err, "Couldn't start impersonation."),
      );
    } finally {
      setPending(false);
    }
  }, [getApiToken, userId]);

  const onCopy = React.useCallback(async () => {
    if (!grant) return;
    try {
      await navigator.clipboard.writeText(grant.token);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be unavailable; the token stays visible for manual copy.
    }
  }, [grant]);

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant="outline"
        size="sm"
        onClick={() => void onImpersonate()}
        disabled={pending}
        aria-label={label ? `Impersonate ${label}` : "Impersonate user"}
      >
        {pending ? (
          <Loader2 className="size-4 animate-spin" aria-hidden />
        ) : (
          <UserCog className="size-4" aria-hidden />
        )}
        Impersonate
      </Button>

      {error && (
        <span className="text-xs text-destructive" role="alert">
          {error}
        </span>
      )}

      {grant && (
        <div className="mt-1 flex max-w-[16rem] items-center gap-2 rounded-md border border-border bg-secondary/40 px-2 py-1">
          <code className="truncate font-mono text-xs" title={grant.token}>
            {grant.token}
          </code>
          <button
            type="button"
            onClick={() => void onCopy()}
            className="shrink-0 text-muted-foreground hover:text-foreground"
            aria-label="Copy impersonation token"
          >
            {copied ? (
              <Check className="size-3.5 text-success" aria-hidden />
            ) : (
              <Copy className="size-3.5" aria-hidden />
            )}
          </button>
        </div>
      )}
    </div>
  );
}
