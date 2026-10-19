"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth, UserButton } from "@/components/auth/clerk-safe";
import { AlertTriangle, Boxes, GitCompareArrows, RefreshCw } from "lucide-react";

import { ApiError } from "@/lib/api";
import {
  formatUsdMicros,
  listCatalogModels,
  type CatalogModel,
} from "@/lib/marketplace";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

const CAPABILITIES = ["", "script", "voice", "avatar", "broll", "image", "music"];

export default function ModelsPage() {
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [models, setModels] = React.useState<CatalogModel[]>([]);
  const [capability, setCapability] = React.useState<string>("");
  const [errorMessage, setErrorMessage] = React.useState<string>("");

  const load = React.useCallback(
    async (cap: string) => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = (await getToken()) ?? undefined;
        setModels(await listCatalogModels({ token }, cap || undefined));
        setStatus("ready");
      } catch (err) {
        setErrorMessage(
          friendlyErrorMessage(err, "Failed to load the model catalog."),
        );
        setStatus("error");
      }
    },
    [getToken],
  );

  React.useEffect(() => {
    if (isLoaded) void load(capability);
  }, [isLoaded, capability, load]);

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Boxes className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Model catalog</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <Link href="/models/compare">
              <GitCompareArrows className="mr-2 h-4 w-4" aria-hidden /> Compare
            </Link>
          </Button>
          <Button variant="outline" size="sm" onClick={() => void load(capability)}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden /> Refresh
          </Button>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <div className="mb-4 flex flex-wrap gap-2">
        {CAPABILITIES.map((cap) => (
          <button
            key={cap || "all"}
            type="button"
            onClick={() => setCapability(cap)}
            className={`rounded-full border px-3 py-1 text-sm capitalize transition ${
              capability === cap
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            {cap || "all"}
          </button>
        ))}
      </div>

      {status === "loading" && (
        <div className="space-y-2">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}

      {status === "error" && (
        <Card>
          <CardContent className="flex items-center gap-3 py-6 text-destructive">
            <AlertTriangle className="h-5 w-5" aria-hidden />
            <p>{errorMessage}</p>
          </CardContent>
        </Card>
      )}

      {status === "ready" && models.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No models are published for this capability yet.
          </CardContent>
        </Card>
      )}

      {status === "ready" && models.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {models.map((model) => (
            <Card key={model.model_id}>
              <CardContent className="py-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{model.display_name || model.model_id}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {model.provider.display_name || model.provider.provider_key} ·{" "}
                      <span className="capitalize">{model.capability}</span>
                    </p>
                  </div>
                  <span className="shrink-0 rounded-full border px-2 py-0.5 text-xs capitalize text-muted-foreground">
                    {model.availability_state}
                  </span>
                </div>
                {model.description && (
                  <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">
                    {model.description}
                  </p>
                )}
                <div className="mt-3 flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">
                    {model.price?.unit ? `per ${model.price.unit}` : model.metering_unit}
                  </span>
                  <span className="tabular-nums font-medium">
                    {model.price?.unit_price_micros != null
                      ? formatUsdMicros(model.price.unit_price_micros)
                      : "—"}
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </main>
  );
}
