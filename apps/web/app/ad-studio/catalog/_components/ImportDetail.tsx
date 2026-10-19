"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, ExternalLink, ImageOff } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ChipToggle, ErrorText, LoadError, errorMessage, toggleIn, useRequestOptions } from "@/src/features/ad-studio/shared";
import { DASH, formatMinor } from "@/src/features/ads/format";
import { safeServerText } from "@/src/shared/errors";
import {
  MAX_PROJECTS_PER_CALL,
  createProjects,
  getImport,
  providerLabel,
  type ProjectResult,
  type StoreImportDetail,
  type StoreProduct,
} from "./api";

function price(p: StoreProduct): string {
  if (p.price_minor === null) return DASH;
  return p.currency ? formatMinor(p.price_minor, p.currency) : String(p.price_minor / 100);
}

/** Products from one store import; pick up to five and send them to Ad Studio. */
export function ImportDetail({ importId }: { importId: string }) {
  const requestOptions = useRequestOptions();
  const [data, setData] = React.useState<StoreImportDetail | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const [selected, setSelected] = React.useState<string[]>([]);
  const [useLlm, setUseLlm] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [actionError, setActionError] = React.useState("");
  const [results, setResults] = React.useState<ProjectResult[]>([]);

  const load = React.useCallback(async () => {
    try {
      setData(await getImport(importId, await requestOptions()));
      setError(null);
    } catch (err) {
      setError(err);
    }
  }, [importId, requestOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function send() {
    setBusy(true);
    setActionError("");
    try {
      const out = await createProjects(importId, { product_ids: selected, use_llm: useLlm }, await requestOptions());
      setResults(out.results);
      setSelected([]);
      await load();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!data && !error) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-64" />
        ))}
      </div>
    );
  }
  if (!data) {
    return (
      <LoadError
        error={error}
        onRetry={() => {
          setError(null);
          void load();
        }}
        fallback="We couldn't load this store import. Please try again."
      />
    );
  }

  const failures = results.filter((r) => r.error);
  const byId = new Map(data.products.map((p) => [p.id, p]));

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Link href="/ad-studio/catalog" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
          <ArrowLeft className="h-4 w-4" aria-hidden />
          All imports
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold">{data.store_name || data.store_url}</h1>
          <Badge variant="outline">{providerLabel(data.provider)}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          {data.product_count} products imported, {data.created_projects ?? 0} already in Ad Studio.
        </p>
      </div>

      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded-lg border bg-background/95 p-3 backdrop-blur">
        <span className="text-sm">
          {selected.length} of {MAX_PROJECTS_PER_CALL} selected
        </span>
        <ChipToggle selected={useLlm} onToggle={() => setUseLlm((v) => !v)} title="Uses the AI writer; slower">
          Draft angles with AI
        </ChipToggle>
        <Button onClick={send} disabled={busy || selected.length === 0}>
          {busy ? "Creating projects..." : "Create Ad Studio projects"}
        </Button>
        <p className="text-xs text-muted-foreground">Product images are copied into your media library.</p>
      </div>
      <ErrorText message={actionError} />
      {failures.length ? (
        <ul className="space-y-1 text-sm text-destructive" role="alert">
          {failures.map((f) => (
            <li key={f.product_id}>
              {byId.get(f.product_id)?.title ?? "A product"}: {safeServerText(f.error, "could not be added.")}
            </li>
          ))}
        </ul>
      ) : null}

      {data.products.length === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">This import has no products.</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.products.map((p) => {
            const isSelected = selected.includes(p.id);
            const full = !isSelected && selected.length >= MAX_PROJECTS_PER_CALL;
            return (
              <li key={p.id} className="flex flex-col overflow-hidden rounded-lg border">
                <div className="flex aspect-square items-center justify-center bg-secondary/40">
                  {p.image_urls[0] ? (
                    // Store CDN images are shown as-is; they are only copied on project creation.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={p.image_urls[0]} alt={p.title} loading="lazy" className="h-full w-full object-cover" />
                  ) : (
                    <ImageOff className="h-8 w-8 text-muted-foreground" aria-label="No image" />
                  )}
                </div>
                <div className="flex flex-1 flex-col gap-2 p-3">
                  <p className="line-clamp-2 text-sm font-medium">{p.title}</p>
                  <p className="text-sm tabular-nums">
                    {price(p)}
                    {p.compare_at_minor !== null && p.currency ? (
                      <span className="ml-2 text-xs text-muted-foreground line-through">
                        {formatMinor(p.compare_at_minor, p.currency)}
                      </span>
                    ) : null}
                  </p>
                  <div className="mt-auto flex flex-wrap items-center justify-between gap-2">
                    {p.adstudio_project_id ? (
                      <Link href={`/ad-studio/${p.adstudio_project_id}`} className="text-sm text-primary hover:underline">
                        Open in Ad Studio
                      </Link>
                    ) : (
                      <ChipToggle
                        selected={isSelected}
                        disabled={full}
                        onToggle={() => setSelected((prev) => toggleIn(prev, p.id))}
                        title={full ? `Up to ${MAX_PROJECTS_PER_CALL} at a time` : undefined}
                      >
                        {isSelected ? "Selected" : "Select"}
                      </ChipToggle>
                    )}
                    {p.url ? (
                      <a href={p.url} target="_blank" rel="noopener noreferrer" className="text-muted-foreground"
                        aria-label={`View ${p.title} in the store`}>
                        <ExternalLink className="h-4 w-4" aria-hidden />
                      </a>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
