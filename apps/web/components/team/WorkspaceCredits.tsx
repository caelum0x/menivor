"use client";

import * as React from "react";
import { AlertCircle, Coins, Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspaceCredits } from "@/components/team/use-workspace-credits";

interface WorkspaceCreditsProps {
  workspaceId: string;
  /** Whether the caller may grant credits (owner/admin). */
  canManage: boolean;
}

/**
 * The workspace SHARED credit pool panel: shows the current balance any member
 * can see, plus an owner/admin-only grant control to top it up. Members can
 * charge new reels to this pool from the wizard. Loading, empty, and error
 * states are surfaced inline; a failed grant never blanks the balance.
 */
export function WorkspaceCredits({
  workspaceId,
  canManage,
}: Readonly<WorkspaceCreditsProps>) {
  const {
    status,
    balance,
    errorMessage,
    granting,
    grantError,
    reload,
    grant,
  } = useWorkspaceCredits(workspaceId);

  return (
    <div className="rounded-lg border border-border bg-secondary/30 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <Coins className="size-4 text-primary" aria-hidden />
            Shared credits
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            A pool the whole team can charge reels to.
          </p>
        </div>
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

      <div className="mt-3">
        {status === "loading" && <Skeleton className="h-9 w-28" />}

        {status === "error" && (
          <p
            role="alert"
            className="flex items-center gap-2 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            {errorMessage}
          </p>
        )}

        {status === "ready" && (
          <p className="flex items-baseline gap-2">
            <span className="text-3xl font-bold tabular-nums tracking-tight">
              {(balance ?? 0).toLocaleString()}
            </span>
            <span className="text-sm text-muted-foreground">credits</span>
          </p>
        )}
      </div>

      {canManage && (
        <GrantForm granting={granting} grantError={grantError} onGrant={grant} />
      )}
    </div>
  );
}

interface GrantFormProps {
  granting: boolean;
  grantError: string;
  /** Grant `amount` credits; resolves true on success (resets the form). */
  onGrant: (amount: number, reason?: string) => Promise<boolean>;
}

/** Owner/admin-only control to add credits to the shared pool. */
function GrantForm({ granting, grantError, onGrant }: Readonly<GrantFormProps>) {
  const [amount, setAmount] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [localError, setLocalError] = React.useState<string | null>(null);

  const parsed = Number.parseInt(amount, 10);
  const isValid = Number.isFinite(parsed) && parsed > 0;

  const handleSubmit = React.useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setLocalError(null);
      if (!isValid) {
        setLocalError("Enter a whole number of credits greater than zero.");
        return;
      }
      const ok = await onGrant(parsed, reason);
      if (ok) {
        setAmount("");
        setReason("");
      }
    },
    [isValid, onGrant, parsed, reason],
  );

  return (
    <form onSubmit={handleSubmit} className="mt-4 border-t border-border pt-4">
      <div className="grid gap-3 sm:grid-cols-[8rem_1fr_auto] sm:items-end">
        <div className="grid gap-1.5">
          <Label htmlFor="grant-amount">Amount</Label>
          <Input
            id="grant-amount"
            type="number"
            inputMode="numeric"
            min={1}
            step={1}
            placeholder="100"
            value={amount}
            disabled={granting}
            onChange={(e) => setAmount(e.target.value)}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="grant-reason">Reason (optional)</Label>
          <Input
            id="grant-reason"
            placeholder="e.g. Q3 top-up"
            value={reason}
            maxLength={120}
            disabled={granting}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={granting || !isValid}>
          <Plus aria-hidden />
          {granting ? "Granting…" : "Grant"}
        </Button>
      </div>

      {(localError || grantError) && (
        <p
          role="alert"
          className="mt-2 flex items-center gap-2 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {localError ?? grantError}
        </p>
      )}
    </form>
  );
}
