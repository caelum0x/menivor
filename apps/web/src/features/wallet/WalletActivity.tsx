"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth, UserButton } from "@/components/auth/clerk-safe";
import { AlertTriangle, ArrowLeft, ReceiptText, RefreshCw } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { WalletNav } from "@/components/wallet/WalletNav";
import { formatUsdMicros, getLedger, type LedgerEntry } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

const PAGE_SIZE = 25;

const ENTRY_LABEL: Record<string, string> = {
  grant: "Credit added",
  topup: "Top-up",
  reserve: "Reserved for job",
  settle: "Job charge",
  release: "Reservation released",
  refund: "Refund",
  adjustment: "Adjustment",
};

function labelFor(entryType: string): string {
  return ENTRY_LABEL[entryType] ?? entryType;
}

/** Wallet ledger — paginated burn/spend/grant rows, newest first. */
export function WalletActivity() {
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [rows, setRows] = React.useState<LedgerEntry[]>([]);
  const [error, setError] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const [hasMore, setHasMore] = React.useState(false);
  const [loadingMore, setLoadingMore] = React.useState(false);

  const loadFirst = React.useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const page = await getLedger({ limit: PAGE_SIZE, offset: 0 }, { token });
      setRows(page.entries);
      setOffset(page.entries.length);
      setHasMore(page.entries.length >= PAGE_SIZE);
      setStatus("ready");
    } catch (err) {
      setError(
        friendlyErrorMessage(err, "Failed to load wallet activity."),
      );
      setStatus("error");
    }
  }, [getToken]);

  const loadMore = React.useCallback(async () => {
    setLoadingMore(true);
    try {
      const token = (await getToken()) ?? undefined;
      const page = await getLedger({ limit: PAGE_SIZE, offset }, { token });
      setRows((prev) => [...prev, ...page.entries]);
      setOffset((prev) => prev + page.entries.length);
      setHasMore(page.entries.length >= PAGE_SIZE);
    } catch (err) {
      setError(
        friendlyErrorMessage(err, "Failed to load more activity."),
      );
    } finally {
      setLoadingMore(false);
    }
  }, [getToken, offset]);

  React.useEffect(() => {
    if (isLoaded) void loadFirst();
  }, [isLoaded, loadFirst]);

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ReceiptText className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Wallet activity</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void loadFirst()}
            disabled={status === "loading"}
          >
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden /> Refresh
          </Button>
          <Link
            href="/wallet"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden /> Wallet
          </Link>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <WalletNav />

      {status === "loading" && (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      )}

      {status === "error" && (
        <Card>
          <CardContent className="flex items-center gap-3 py-6 text-destructive">
            <AlertTriangle className="h-5 w-5" aria-hidden />
            <div>
              <p>{error}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => void loadFirst()}
              >
                Try again
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {status === "ready" && rows.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No wallet activity yet. Add credit to get started.
          </CardContent>
        </Card>
      )}

      {status === "ready" && rows.length > 0 && (
        <>
          <ul className="divide-y rounded-lg border">
            {rows.map((row, index) => {
              const positive = row.amount_micros > 0;
              return (
                <li
                  key={row.id || `${index}`}
                  className="flex items-center justify-between gap-4 px-4 py-3"
                >
                  <div className="min-w-0">
                    <p className="font-medium">{labelFor(row.entry_type)}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {row.reason}
                      {row.job_id ? ` · job ${row.job_id.slice(0, 8)}` : ""}
                      {row.created_at
                        ? ` · ${new Date(row.created_at).toLocaleString()}`
                        : ""}
                    </p>
                  </div>
                  <div className="text-right">
                    <p
                      className={`tabular-nums font-medium ${
                        positive ? "text-emerald-600" : "text-foreground"
                      }`}
                    >
                      {positive ? "+" : ""}
                      {formatUsdMicros(row.amount_micros)}
                    </p>
                    {row.balance_after_micros !== null && (
                      <p className="text-xs text-muted-foreground tabular-nums">
                        bal {formatUsdMicros(row.balance_after_micros)}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          {hasMore && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                onClick={() => void loadMore()}
                disabled={loadingMore}
              >
                {loadingMore ? "Loading…" : "Load more"}
              </Button>
            </div>
          )}
        </>
      )}
    </main>
  );
}
