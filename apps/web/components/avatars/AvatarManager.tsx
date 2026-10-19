"use client";

import * as React from "react";
import { AlertTriangle, RefreshCw, UserSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AvatarCard } from "@/components/avatars/AvatarCard";
import { CreateAvatarForm } from "@/components/avatars/CreateAvatarForm";
import { useMyAvatars } from "@/components/avatars/use-my-avatars";

/**
 * The custom-avatar manager page body: a create-from-photo form on the left and
 * the caller's custom avatars on the right, with loading / error / empty states.
 */
export function AvatarManager() {
  const { status, avatars, errorMessage, reload, prepend } = useMyAvatars();

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,380px)_1fr]">
      <div className="lg:sticky lg:top-6 lg:self-start">
        <CreateAvatarForm onCreated={prepend} />
      </div>

      <div>
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold tracking-tight">
            Your avatars
            {status === "ready" && avatars.length > 0 && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                {avatars.length}
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

        {status === "loading" && <AvatarsSkeleton />}

        {status === "error" && (
          <ErrorPanel message={errorMessage} onRetry={reload} />
        )}

        {status === "ready" && avatars.length === 0 && <EmptyState />}

        {status === "ready" && avatars.length > 0 && (
          <ul className="grid gap-4 sm:grid-cols-2">
            {avatars.map((avatar) => (
              <li key={avatar.avatar_id}>
                <AvatarCard avatar={avatar} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function AvatarsSkeleton() {
  return (
    <ul className="grid gap-4 sm:grid-cols-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <li key={i}>
          <Card>
            <CardContent className="flex items-center gap-3 p-4">
              <Skeleton className="size-14 shrink-0 rounded-md" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-1/3" />
              </div>
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
            <p className="font-medium">Couldn&apos;t load your avatars</p>
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
          <UserSquare className="size-6 text-primary" aria-hidden />
        </span>
        <div>
          <p className="font-medium">No custom avatars yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Upload a clear selfie to turn it into a talking-photo avatar, then
            pick it as the presenter on any reel.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
