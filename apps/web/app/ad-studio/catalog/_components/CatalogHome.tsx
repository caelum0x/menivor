"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Store, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorText, LoadError, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { isHumanReadable } from "@/src/shared/errors";
import { formatWhen } from "@/src/features/ads/format";
import {
  MAX_PRODUCTS_PER_IMPORT,
  createImport,
  deleteImport,
  listImports,
  providerLabel,
  type ProviderChoice,
  type StoreImport,
} from "./api";

/** Paste a store URL, import its products, and browse earlier imports. */
export function CatalogHome() {
  const router = useRouter();
  const requestOptions = useRequestOptions();
  const [imports, setImports] = React.useState<StoreImport[] | null>(null);
  const [listError, setListError] = React.useState<unknown>(null);
  const [url, setUrl] = React.useState("");
  const [provider, setProvider] = React.useState<ProviderChoice>("auto");
  const [limit, setLimit] = React.useState("50");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const data = await listImports(await requestOptions());
      setImports(data.imports);
      setListError(null);
    } catch (err) {
      setListError(err);
    }
  }, [requestOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const count = Math.round(Number(limit));
    if (!url.trim()) {
      setError("Paste your store's address, for example yourstore.com.");
      return;
    }
    if (!Number.isFinite(count) || count < 1 || count > MAX_PRODUCTS_PER_IMPORT) {
      setError(`Import between 1 and ${MAX_PRODUCTS_PER_IMPORT} products.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await createImport({ store_url: url.trim(), provider, limit: count }, await requestOptions());
      router.push(`/ad-studio/catalog/${created.id}`);
    } catch (err) {
      setError(errorMessage(err));
      void load(); // the failed attempt is kept in history with its reason
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    try {
      await deleteImport(id, await requestOptions());
      setImports((prev) => (prev ?? []).filter((i) => i.id !== id));
    } catch (err) {
      setListError(err);
    }
  }

  return (
    <div className="space-y-8">
      <form onSubmit={submit} className="space-y-4 rounded-lg border p-4">
        <div className="grid gap-3 md:grid-cols-[1fr_12rem_8rem]">
          <div className="space-y-1">
            <Label htmlFor="store-url">Store address</Label>
            <Input
              id="store-url"
              placeholder="yourstore.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              autoComplete="url"
              inputMode="url"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="store-provider">Platform</Label>
            <Select id="store-provider" value={provider} onChange={(e) => setProvider(e.target.value as ProviderChoice)}>
              <option value="auto">Auto-detect</option>
              <option value="shopify">Shopify</option>
              <option value="woocommerce">WooCommerce</option>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="store-limit">Products</Label>
            <Input
              id="store-limit"
              type="number"
              min={1}
              max={MAX_PRODUCTS_PER_IMPORT}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
            />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={busy}>
            <Store className="mr-1 h-4 w-4" aria-hidden />
            {busy ? "Reading the store..." : "Import products"}
          </Button>
          <p className="text-xs text-muted-foreground">
            Reads the store&apos;s public product feed. No store login or admin key is needed. Password-protected stores
            cannot be read.
          </p>
        </div>
        <ErrorText message={error} />
      </form>

      <section aria-labelledby="catalog-imports" className="space-y-3">
        <h2 id="catalog-imports" className="text-lg font-semibold">
          Imports
        </h2>
        {imports === null && !listError ? <Skeleton className="h-24" /> : null}
        {listError ? (
          <LoadError error={listError} onRetry={() => void load()} fallback="We couldn't load your imports. Please try again." />
        ) : null}
        {imports && imports.length === 0 ? (
          <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
            No imports yet. Paste your store address above to pull in its products.
          </p>
        ) : null}
        {imports && imports.length > 0 ? (
          <ul className="divide-y rounded-lg border">
            {imports.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {row.status === "succeeded" ? (
                      <Link href={`/ad-studio/catalog/${row.id}`} className="font-medium underline-offset-4 hover:underline">
                        {row.store_name || row.store_url}
                      </Link>
                    ) : (
                      <span className="font-medium">{row.store_name || row.store_url}</span>
                    )}
                    <Badge variant="outline">
                      {row.status === "failed" ? providerLabel(row.provider_requested) : providerLabel(row.provider)}
                    </Badge>
                    {row.status === "failed" ? <Badge variant="destructive">Failed</Badge> : null}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {row.status === "failed"
                      ? row.error && isHumanReadable(row.error)
                        ? row.error
                        : "We couldn't read this store."
                      : `${row.product_count} products, ${row.created_projects ?? 0} in Ad Studio`}
                    {" · "}
                    {formatWhen(row.created_at)}
                  </p>
                </div>
                <Button variant="ghost" size="sm" aria-label={`Delete import of ${row.store_name || row.store_url}`}
                  onClick={() => remove(row.id)}>
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
}
