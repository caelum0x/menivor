"use client";

// Reel-create presentation component.

import * as React from "react";
import { AlertCircle, Wallet } from "lucide-react";
import { getMe, getWorkspaceCredits } from "@/lib/api";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiToken } from "@/lib/use-api-token";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";

interface ChargeToSelectorProps {
  /** Selected workspace id, or null for the caller's personal credits. */
  value: string | null;
  /** Called with the new selection (a workspace id, or null for personal). */
  onChange: (workspaceId: string | null) => void;
}

const PERSONAL = "__personal__";

type BalanceState =
  | { status: "loading" }
  | { status: "ready"; balance: number }
  | { status: "error"; message: string };

/**
 * Lets the creator choose which credit pool to charge the reel to: their own
 * personal balance, or a workspace's SHARED pool (any workspace they belong to).
 * Shows the relevant balance for the current selection. The chosen workspace id
 * (or null) flows up as `params.workspace_id` on the created job; the backend
 * enforces membership and debits the right pool.
 */
export function ChargeToSelector({
  value,
  onChange,
}: Readonly<ChargeToSelectorProps>) {
  const getApiToken = useApiToken();
  const { status: wsStatus, workspaces } = useMyWorkspaces();
  const [balance, setBalance] = React.useState<BalanceState>({
    status: "loading",
  });

  // Load the balance for the current selection (personal via /me, workspace via
  // /workspaces/{id}/credits). Re-runs whenever the selection changes.
  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async (): Promise<void> => {
      setBalance({ status: "loading" });
      try {
        const token = await getApiToken();
        const options = { token, signal: controller.signal };
        const next = value
          ? (await getWorkspaceCredits(value, options)).balance
          : (await getMe(options)).credits;
        if (!cancelled) setBalance({ status: "ready", balance: next });
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setBalance({
          status: "error",
          message: "Couldn't load the balance for this pool.",
        });
      }
    };

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, value]);

  // If the selected workspace disappears from the list (e.g. left the team),
  // fall back to personal so we never charge an inaccessible pool.
  React.useEffect(() => {
    if (wsStatus !== "ready" || value === null) return;
    if (!workspaces.some((w) => w.id === value)) onChange(null);
  }, [wsStatus, workspaces, value, onChange]);

  const handleChange = React.useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const raw = e.target.value;
      onChange(raw === PERSONAL ? null : raw);
    },
    [onChange],
  );

  return (
    <div className="grid gap-1.5">
      <Label htmlFor="charge-to" className="flex items-center gap-2">
        <Wallet className="size-4 text-primary" aria-hidden />
        Charge to
      </Label>
      <Select
        id="charge-to"
        value={value ?? PERSONAL}
        disabled={wsStatus === "loading"}
        onChange={handleChange}
      >
        <option value={PERSONAL}>Personal credits</option>
        {workspaces.map((w) => (
          <option key={w.id} value={w.id}>
            {w.name} (shared)
          </option>
        ))}
      </Select>

      <div className="min-h-5 text-xs">
        {balance.status === "loading" && (
          <Skeleton className="h-4 w-32" />
        )}
        {balance.status === "ready" && (
          <p className="text-muted-foreground">
            Balance:{" "}
            <span className="font-medium text-foreground tabular-nums">
              {balance.balance.toLocaleString()}
            </span>{" "}
            credits
          </p>
        )}
        {balance.status === "error" && (
          <p
            role="alert"
            className="flex items-center gap-1.5 text-destructive"
          >
            <AlertCircle className="size-3.5 shrink-0" aria-hidden />
            {balance.message}
          </p>
        )}
      </div>
    </div>
  );
}
