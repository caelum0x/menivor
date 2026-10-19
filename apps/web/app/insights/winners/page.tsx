"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { AlertTriangle, RefreshCw, Trophy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessageOf, getLoopBoard, WinnersBoard, type LoopBoard } from "@/src/features/insights";

type LoadState = "loading" | "ready" | "error";

/** Growth › Winner loop — post variants, read the numbers, remake the winner. */
export default function WinnersPage() {
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [board, setBoard] = React.useState<LoopBoard | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = (await getToken()) ?? undefined;
      setBoard(await getLoopBoard({ token }));
      setStatus("ready");
    } catch (err) {
      setErrorMessage(errorMessageOf(err, "Something went wrong loading your winner loop."));
      setStatus("error");
    }
  }, [getToken]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  return (
    <>
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Trophy className="size-6 text-primary" aria-hidden />
            Winner loop
          </h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Post your variants, read the real numbers after 48 hours, and remake the one that
            won into three new hooks.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={status === "loading"}>
          <RefreshCw className={status === "loading" ? "size-4 animate-spin" : "size-4"} aria-hidden />
          Refresh
        </Button>
      </div>

      {status === "loading" && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="space-y-3 p-5">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-5 w-full" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-12 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {status === "error" && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
              <div>
                <p className="font-medium">Couldn&apos;t load the winner loop</p>
                <p className="text-sm text-muted-foreground">{errorMessage}</p>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              <RefreshCw className="size-4" aria-hidden /> Try again
            </Button>
          </CardContent>
        </Card>
      )}

      {status === "ready" && board && <WinnersBoard board={board} />}
    </>
  );
}
