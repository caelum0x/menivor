"use client";

import * as React from "react";
import { AlertTriangle, Mic, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CloneVoiceForm } from "@/components/voices/CloneVoiceForm";
import { VoiceCard } from "@/components/voices/VoiceCard";
import { useMyVoices } from "@/components/voices/use-my-voices";

/**
 * The Brand Voice manager page body: a clone form on the left and the caller's
 * cloned voices on the right, with loading / error / empty states and delete.
 */
export function VoiceManager() {
  const { status, voices, errorMessage, reload, prepend, remove } =
    useMyVoices();

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,380px)_1fr]">
      <div className="lg:sticky lg:top-6 lg:self-start">
        <CloneVoiceForm onCreated={prepend} />
      </div>

      <div>
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold tracking-tight">
            Your brand voices
            {status === "ready" && voices.length > 0 && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                {voices.length}
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

        {status === "loading" && <VoicesSkeleton />}

        {status === "error" && (
          <ErrorPanel message={errorMessage} onRetry={reload} />
        )}

        {status === "ready" && voices.length === 0 && <EmptyState />}

        {status === "ready" && voices.length > 0 && (
          <ul className="grid gap-4 sm:grid-cols-2">
            {voices.map((voice) => (
              <li key={voice.id}>
                <VoiceCard voice={voice} onDelete={remove} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function VoicesSkeleton() {
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
            <p className="font-medium">Couldn&apos;t load your brand voices</p>
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
          <Mic className="size-6 text-primary" aria-hidden />
        </span>
        <div>
          <p className="font-medium">No brand voices yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Record or upload a short sample to clone your own voice, then pick it
            as the narrator on any reel.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
