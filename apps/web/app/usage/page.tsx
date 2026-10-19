"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth, UserButton } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  Gauge,
  KeyRound,
  RefreshCw,
} from "lucide-react";
import { ApiError, getApiKeyUsage } from "@/lib/api";
import type { ApiKeyUsage } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { UsageList } from "@/components/usage/UsageCard";
import { MenivorMark } from "@/components/brand/MenivorMark";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

export default function UsagePage() {
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [usage, setUsage] = React.useState<ApiKeyUsage[]>([]);
  const [errorMessage, setErrorMessage] = React.useState<string>("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = (await getToken()) ?? undefined;
      const result = await getApiKeyUsage({ token });
      setUsage(result);
      setStatus("ready");
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Something went wrong loading your API-key usage.");
      setErrorMessage(message);
      setStatus("error");
    }
  }, [getToken]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <div className="flex items-center gap-3">
            <Button asChild variant="outline" size="sm">
              <Link href="/reels">Your reels</Link>
            </Button>
            <UserButton />
          </div>
        </div>
      </header>

      <section className="container py-8">
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              <Gauge className="size-6 text-primary" aria-hidden />
              API usage
            </h1>
            <p className="text-sm text-muted-foreground">
              Per-key rate limits, monthly quotas, and requests used this month.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={status === "loading" ? "size-4 animate-spin" : "size-4"}
              aria-hidden
            />
            Refresh
          </Button>
        </div>

        {status === "loading" && <UsageSkeleton />}

        {status === "error" && (
          <ErrorPanel message={errorMessage} onRetry={() => void load()} />
        )}

        {status === "ready" &&
          (usage.length > 0 ? (
            <UsageList usage={usage} />
          ) : (
            <EmptyPanel />
          ))}
      </section>
    </main>
  );
}

function UsageSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <Card key={i}>
          <CardContent className="space-y-4 p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="w-full space-y-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-20" />
              </div>
              <Skeleton className="h-6 w-20 rounded-full" />
            </div>
            <Skeleton className="h-2 w-full rounded-full" />
            <Skeleton className="h-3 w-40" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function EmptyPanel() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <KeyRound className="size-6" aria-hidden />
        </span>
        <div>
          <p className="font-medium">No API keys yet</p>
          <p className="text-sm text-muted-foreground">
            Mint a personal API key to call Menivor programmatically. Usage and
            quotas will show up here.
          </p>
        </div>
      </CardContent>
    </Card>
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
            <p className="font-medium">Couldn&apos;t load your API usage</p>
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
