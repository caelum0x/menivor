"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

interface RouteErrorProps {
  readonly error: Error & { digest?: string };
  readonly reset: () => void;
  /** Section name for the heading, e.g. "your inbox". Omit for a generic page. */
  readonly section?: string;
}

/**
 * Shared route-segment error state: an unexpected failure while rendering or
 * loading a section shows a recoverable screen instead of a blank one. The
 * error is logged to the console; the digest (server errors) is shown so
 * support can find the matching log line.
 */
export function RouteError({ error, reset, section }: RouteErrorProps) {
  React.useEffect(() => {
    console.error(`[menivor] route error${section ? ` (${section})` : ""}`, error);
  }, [error, section]);

  return (
    <main className="container flex min-h-[60dvh] flex-col items-start justify-center gap-4 py-20">
      <AlertTriangle className="h-8 w-8 text-destructive" aria-hidden />
      <h1 className="text-2xl font-bold tracking-tight">
        {section ? `We couldn't load ${section}` : "Something went wrong on this page"}
      </h1>
      <p className="max-w-lg text-muted-foreground">
        Your reels and credits are safe. Try again, and if it keeps happening contact support
        {error.digest ? (
          <>
            {" "}with reference <code className="font-mono text-xs">{error.digest}</code>
          </>
        ) : null}
        .
      </p>
      <div className="flex flex-wrap gap-2">
        <Button onClick={reset}>
          <RefreshCw className="mr-2 h-4 w-4" aria-hidden /> Try again
        </Button>
        <Button asChild variant="outline">
          <Link href="/reels">My reels</Link>
        </Button>
        <Button asChild variant="ghost">
          <Link href="/contact">Contact support</Link>
        </Button>
      </div>
    </main>
  );
}
