"use client";

import * as React from "react";
import Link from "next/link";
import { Package } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  importCsv,
  importMedusa,
  importShopify,
  resyncProducts,
  validateSecret,
  type ProductImport,
} from "../_lib/api";
import type { SectionProps } from "./AdAccountsSection";

type Source = "shopify" | "medusa" | "csv";

const SOURCES: ReadonlyArray<{ key: Source; title: string; body: string }> = [
  { key: "shopify", title: "Shopify", body: "Admin API token from a custom app with read_products." },
  { key: "medusa", title: "Medusa", body: "Store API with a publishable key (for example Oxhan Atelier)." },
  { key: "csv", title: "CSV or link", body: "Paste a CSV or a link to one. Shopier exports work as they are." },
];

/** Product sources: feed a catalog so URL to Video and Image Ad start from real inventory and pricing. */
export function ProductSourcesSection({ data, scope, getToken, onChanged }: SectionProps) {
  const [open, setOpen] = React.useState<Source | null>(null);
  const [fields, setFields] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [done, setDone] = React.useState<ProductImport | null>(null);
  const field = (key: string) => fields[key] ?? "";
  const set = (key: string) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setFields((current) => ({ ...current, [key]: event.target.value }));

  const resync = async (provider: "shopify" | "medusa") => {
    setBusy(true);
    try {
      setDone(await resyncProducts(provider, scope, { token: (await getToken()) ?? "" }));
      onChanged();
    } catch (err) {
      setError(friendlyErrorMessage(err, "The import did not work."));
    } finally {
      setBusy(false);
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    const secretError = open === "shopify" ? validateSecret(field("token"), "Shopify token")
      : open === "medusa" ? validateSecret(field("key"), "publishable key") : null;
    if (secretError) {
      setError(secretError);
      return;
    }
    setBusy(true);
    try {
      const options = { token: (await getToken()) ?? "" };
      const out = open === "shopify" ? await importShopify(field("shop"), field("token"), scope, options)
        : open === "medusa" ? await importMedusa(field("base"), field("key"), field("storefront"), scope, options)
          : await importCsv({ text: field("csv"), url: field("csvUrl"), currency: field("currency") || "USD" }, scope,
            options);
      setDone(out);
      setFields({});
      setOpen(null);
      onChanged();
    } catch (err) {
      setError(friendlyErrorMessage(err, "The import did not work."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="product-sources" className="space-y-4">
      <div>
        <h2 id="product-sources" className="flex items-center gap-2 text-xl font-semibold">
          <Package className="size-5 text-primary" aria-hidden />
          Product sources
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Feed a catalog into Products so URL to Video and Image Ad start from real inventory and pricing.
        </p>
      </div>
      {done ? (
        <p className="text-sm">
          Imported {done.product_count} products from {done.store_name}.{" "}
          <Link href="/ad-studio/catalog" className="text-primary underline underline-offset-4">Open products</Link>
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-3">
        {SOURCES.map((source) => {
          const saved = data.products.sources.find((s) => s.provider === source.key);
          return (
            <Card key={source.key}>
              <CardContent className="flex h-full flex-col gap-3 p-5">
                <h3 className="font-semibold">{source.title}</h3>
                <p className="text-sm text-muted-foreground">{saved ? `Connected: ${saved.name}` : source.body}</p>
                {open === source.key ? (
                  <form onSubmit={(event) => void submit(event)} className="space-y-2">
                    {source.key === "shopify" ? (
                      <>
                        <Input aria-label="Store address" placeholder="my-store.myshopify.com" value={field("shop")}
                          onChange={set("shop")} />
                        <Input aria-label="Admin API token" type="password" autoComplete="off" placeholder="Admin API token"
                          value={field("token")} onChange={set("token")} />
                      </>
                    ) : null}
                    {source.key === "medusa" ? (
                      <>
                        <Input aria-label="Medusa backend URL" placeholder="https://api.your-store.com" value={field("base")}
                          onChange={set("base")} />
                        <Input aria-label="Publishable key" type="password" autoComplete="off" placeholder="pk_..."
                          value={field("key")} onChange={set("key")} />
                        <Input aria-label="Storefront URL" placeholder="https://your-store.com/tr" value={field("storefront")}
                          onChange={set("storefront")} />
                      </>
                    ) : null}
                    {source.key === "csv" ? (
                      <>
                        <Textarea aria-label="CSV text" rows={4} placeholder="title,price,image,url" value={field("csv")}
                          onChange={set("csv")} />
                        <Input aria-label="CSV link" placeholder="or https://.../products.csv" value={field("csvUrl")}
                          onChange={set("csvUrl")} />
                      </>
                    ) : null}
                    <Button type="submit" size="sm" disabled={busy}>Import</Button>
                  </form>
                ) : (
                  <div className="mt-auto">
                    <Button size="sm" variant={saved ? "outline" : "default"} disabled={!data.ads.can_manage}
                      onClick={() => {
                        setError("");
                        if (saved && source.key !== "csv") void resync(source.key);
                        else setOpen(source.key);
                      }}>
                      {saved ? "Import again" : "Connect"}
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
