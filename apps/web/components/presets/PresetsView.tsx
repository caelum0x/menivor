"use client";

import * as React from "react";
import { AlertTriangle, Package, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PresetCard } from "@/components/presets/PresetCard";
import { PresetCreateForm } from "@/components/presets/PresetCreateForm";
import { useCatalogs } from "@/components/presets/use-catalogs";
import { usePresets } from "@/components/presets/use-presets";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";

/**
 * The Brand Kits page body: a create form on the left and the caller's saved
 * presets on the right. Owns both data hooks (presets + catalogs) so the
 * catalogs are fetched once and shared between the form (option lists) and the
 * cards (id → label resolution).
 */
export function PresetsView() {
  const {
    status,
    presets,
    errorMessage,
    reload,
    create,
    remove,
  } = usePresets();
  const {
    status: catalogStatus,
    catalogs,
    labelMaps,
    errorMessage: catalogError,
  } = useCatalogs();
  const { status: workspacesStatus, workspaces } = useMyWorkspaces();

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,380px)_1fr]">
      <div className="lg:sticky lg:top-6 lg:self-start">
        <PresetCreateForm
          onCreate={create}
          catalogs={catalogs}
          catalogStatus={catalogStatus}
          catalogError={catalogError}
          workspaces={workspaces}
          workspacesLoading={workspacesStatus === "loading"}
        />
      </div>

      <div>
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold tracking-tight">
            Saved kits
            {status === "ready" && presets.length > 0 && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                {presets.length}
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

        {status === "loading" && <PresetsSkeleton />}

        {status === "error" && (
          <ErrorPanel message={errorMessage} onRetry={reload} />
        )}

        {status === "ready" && presets.length === 0 && <EmptyState />}

        {status === "ready" && presets.length > 0 && (
          <ul className="grid gap-4 sm:grid-cols-2">
            {presets.map((preset) => (
              <li key={preset.id}>
                <PresetCard
                  preset={preset}
                  labelMaps={labelMaps}
                  onDelete={remove}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function PresetsSkeleton() {
  return (
    <ul className="grid gap-4 sm:grid-cols-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <li key={i}>
          <Card>
            <CardContent className="space-y-3 p-6">
              <Skeleton className="h-5 w-1/2" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
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
            <p className="font-medium">Couldn&apos;t load your presets</p>
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
          <Package className="size-6 text-primary" aria-hidden />
        </span>
        <div>
          <p className="font-medium">No brand kits yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Save your favourite avatar, voice, layout, caption, and music combo
            as a kit to reuse it on every new reel.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
