"use client";

import * as React from "react";
import { Download, Globe, Link2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { importBrandKit, type BrandImportResult, type BrandImportSource, type ImportedBrand } from "./api";

const ORIGIN_LABELS: Record<string, string> = {
  meta: "declared by the site",
  "css-variable": "site brand colour variable",
  stylesheet: "used on the page",
  "google-fonts": "loaded from Google Fonts",
  rally: "from Rally",
};

export interface BrandKitImportProps {
  /** Pre-selected source (e.g. arriving from a Rally share link). */
  initialSource?: BrandImportSource;
  initialValue?: string;
  /** Called after a kit was saved so the caller can refresh its list. */
  onImported?: (result: BrandImportResult) => void;
}

/** Import a brand kit from a website URL or a Rally brand kit share link. */
export function BrandKitImport({ initialSource = "website", initialValue = "", onImported }: BrandKitImportProps) {
  const requestOptions = useRequestOptions();
  const [source, setSource] = React.useState<BrandImportSource>(initialSource);
  const [value, setValue] = React.useState(initialValue);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [result, setResult] = React.useState<BrandImportResult | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    setError("");
    if (!trimmed) {
      setError(source === "website" ? "Paste your website address." : "Paste your Rally brand kit link.");
      return;
    }
    if (source === "website" && !/^https?:\/\//i.test(trimmed)) {
      setError("Paste a full website address starting with https://");
      return;
    }
    setBusy(true);
    try {
      const imported = await importBrandKit({ source, value: trimmed, save: true }, await requestOptions());
      setResult(imported);
      onImported?.(imported);
    } catch (err) {
      setResult(null);
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Import your brand</h2>
          <p className="text-sm text-muted-foreground">
            Read your name, logo, colours and fonts from your website, or bring over the brand kit you set up in
            Rally. Only what we actually find is saved; you can edit the kit afterwards.
          </p>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Brand source">
            <Button
              type="button"
              size="sm"
              variant={source === "website" ? "default" : "outline"}
              onClick={() => setSource("website")}
              disabled={busy}
            >
              <Globe aria-hidden /> From website
            </Button>
            <Button
              type="button"
              size="sm"
              variant={source === "rally" ? "default" : "outline"}
              onClick={() => setSource("rally")}
              disabled={busy}
            >
              <Link2 aria-hidden /> From Rally
            </Button>
          </div>
          <div className="grid gap-1">
            <Label htmlFor="brand-import-value">
              {source === "website" ? "Website address" : "Rally brand kit link or token"}
            </Label>
            <Input
              id="brand-import-value"
              type={source === "website" ? "url" : "text"}
              inputMode="url"
              placeholder={source === "website" ? "https://yourcompany.com" : "Paste the brand kit link or token"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              disabled={busy}
            />
          </div>
          <Button type="submit" disabled={busy}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />}
            {busy ? "Reading brand..." : "Import brand kit"}
          </Button>
          <ErrorText message={error} />
        </form>
        {result ? <ImportedBrandSummary brand={result.brand} kitName={result.preset?.name ?? ""} /> : null}
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-sm">{value}</dd>
    </div>
  );
}

/** What was imported, with where each colour and font came from. */
export function ImportedBrandSummary({ brand, kitName }: { brand: ImportedBrand; kitName?: string }) {
  return (
    <div className="space-y-3 rounded-md border border-border p-4" aria-live="polite">
      <div className="flex items-center gap-3">
        {brand.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- remote logo of arbitrary origin
          <img src={brand.logo_url} alt="" className="h-10 w-10 rounded border border-border object-contain" />
        ) : null}
        <div>
          <p className="font-semibold">{brand.name || brand.website_url}</p>
          {kitName ? <p className="text-xs text-muted-foreground">Saved to brand kit &ldquo;{kitName}&rdquo;</p> : null}
        </div>
      </div>
      <dl className="grid gap-3 sm:grid-cols-2">
        <Row label="Tagline" value={brand.tagline} />
        <Row label="Website" value={brand.website_url} />
        <Row label="Description" value={brand.description} />
        <Row label="Voice" value={brand.voice} />
        <Row label="Audience" value={brand.audience} />
        <Row label="Offer" value={brand.offer} />
      </dl>
      {brand.colors.length > 0 ? (
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Colours</p>
          <ul className="flex flex-wrap gap-2">
            {brand.colors.map((c) => (
              <li key={c.hex} className="flex items-center gap-2 rounded border border-border px-2 py-1 text-xs">
                <span className="h-4 w-4 rounded-sm border border-border" style={{ backgroundColor: c.hex }} aria-hidden />
                <span className="font-mono">{c.hex}</span>
                <span className="text-muted-foreground">{ORIGIN_LABELS[c.origin] ?? c.origin}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No brand colours were published on that page.</p>
      )}
      {brand.fonts.length > 0 ? (
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Fonts</p>
          <ul className="flex flex-wrap gap-2">
            {brand.fonts.map((f) => (
              <li key={f.family} className="rounded border border-border px-2 py-1 text-xs">
                {f.family} <span className="text-muted-foreground">{ORIGIN_LABELS[f.origin] ?? f.origin}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
