"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Bell, Copy, ExternalLink, Loader2, Plus, RefreshCw, Telescope } from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { ErrorText, errorMessage } from "@/src/features/ad-studio/shared";
import { useStableRequestOptions } from "@/src/features/review-queue/use-stable-options";
import {
  TRACKED_BRIEF_KEY,
  addBrand,
  cloneAd,
  dismissAlerts,
  getOverview,
  listAds,
  refreshBrand,
  splitList,
  type CompetitorAd,
  type Overview,
  type Tier,
} from "./api";

const TIERS: { id: Tier | ""; label: string }[] = [
  { id: "", label: "All" },
  { id: "winner", label: "Winners" },
  { id: "proven", label: "Proven" },
  { id: "testing", label: "Testing" },
];
const TIER_LABEL: Record<Tier, string> = { winner: "Winner", proven: "Proven", testing: "Testing", unknown: "New" };
const TIER_VARIANT: Record<Tier, BadgeVariant> = {
  winner: "success",
  proven: "default",
  testing: "secondary",
  unknown: "outline",
};

function AddBrandForm({ onAdded }: { onAdded: () => void }) {
  const requestOptions = useStableRequestOptions();
  const [name, setName] = React.useState("");
  const [pages, setPages] = React.useState("");
  const [advertisers, setAdvertisers] = React.useState("");
  const [terms, setTerms] = React.useState("");
  const [countries, setCountries] = React.useState("DE, FR, NL");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await addBrand(
        {
          name: name.trim(),
          meta_page_ids: splitList(pages),
          tiktok_advertiser_ids: splitList(advertisers),
          search_terms: terms.trim(),
          countries: splitList(countries).map((c) => c.toUpperCase()),
        },
        await requestOptions(),
      );
      setName("");
      setPages("");
      setAdvertisers("");
      setTerms("");
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="glass-subtle space-y-3 rounded-2xl p-4" aria-label="Track a brand">
      <h2 className="font-semibold">Track a brand</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="cb-name">Brand name</Label>
          <Input id="cb-name" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cb-terms">Search words</Label>
          <Input id="cb-terms" value={terms} onChange={(e) => setTerms(e.target.value)} placeholder="cold brew" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cb-pages">Facebook page ids</Label>
          <Input id="cb-pages" value={pages} onChange={(e) => setPages(e.target.value)} inputMode="numeric" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cb-adv">TikTok advertiser ids</Label>
          <Input id="cb-adv" value={advertisers} onChange={(e) => setAdvertisers(e.target.value)} inputMode="numeric" />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="cb-countries">Countries</Label>
          <Input id="cb-countries" value={countries} onChange={(e) => setCountries(e.target.value)} />
        </div>
      </div>
      {error ? <ErrorText message={error} /> : null}
      <Button type="submit" variant="outline" disabled={busy || !name.trim()}>
        {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />} Track brand
      </Button>
    </form>
  );
}

function AdCard({ ad, onClone, busy }: { ad: CompetitorAd; onClone: (ad: CompetitorAd) => void; busy: boolean }) {
  return (
    <article className="glass-subtle flex flex-col gap-3 rounded-2xl p-4" aria-label={`Ad from ${ad.advertiser || ad.brand_name}`}>
      <div className="flex items-center justify-between gap-2">
        <Badge variant={TIER_VARIANT[ad.tier]}>{TIER_LABEL[ad.tier]}</Badge>
        <span className="text-xs text-muted-foreground">
          {ad.days_running === null ? "Start date unknown" : `${ad.days_running} days running`}
          {ad.active ? "" : " (stopped)"}
        </span>
      </div>
      {ad.thumbnail_url ? (
        // eslint-disable-next-line @next/next/no-img-element -- ad-library CDN thumbnail
        <img src={ad.thumbnail_url} alt="" className="aspect-video w-full rounded-xl object-cover" />
      ) : null}
      <div className="space-y-1">
        <p className="text-sm font-medium">{ad.title || ad.advertiser || ad.brand_name}</p>
        <p className="line-clamp-4 text-sm text-muted-foreground">{ad.body || "No copy in the ad library."}</p>
      </div>
      <p className="text-xs text-muted-foreground">
        {ad.source === "meta" ? "Meta Ad Library" : "TikTok ad library"}
        {ad.scaled ? " - running in several versions" : ""}
        {ad.is_new ? " - new" : ""}
      </p>
      <div className="mt-auto flex items-center justify-between gap-2">
        {ad.page_url ? (
          <a
            href={ad.page_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            View in ad library <ExternalLink className="size-3" aria-hidden />
          </a>
        ) : (
          <span />
        )}
        <Button size="sm" variant="outline" onClick={() => onClone(ad)} disabled={busy || !ad.can_clone}>
          <Copy aria-hidden /> Clone this
        </Button>
      </div>
    </article>
  );
}

/** Competitor ads from official ad libraries, ranked by how long they run (the winner signal). */
export function CompetitorTracker() {
  const requestOptions = useStableRequestOptions();
  const router = useRouter();
  const [overview, setOverview] = React.useState<Overview | null>(null);
  const [ads, setAds] = React.useState<CompetitorAd[]>([]);
  const [tier, setTier] = React.useState<Tier | "">("");
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [note, setNote] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const opts = await requestOptions();
      const [ov, list] = await Promise.all([getOverview(opts), listAds(tier, opts)]);
      setOverview(ov);
      setAds(list.ads);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [requestOptions, tier]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const refresh = async (id: string) => {
    setBusy(id);
    setError("");
    try {
      const out = await refreshBrand(id, await requestOptions());
      setNote(out.new ? `${out.new} new ads found.` : "Up to date.");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const clone = async (ad: CompetitorAd) => {
    setBusy(ad.id);
    setError("");
    try {
      const out = await cloneAd(ad.id, await requestOptions());
      window.sessionStorage.setItem(TRACKED_BRIEF_KEY, JSON.stringify({ brief: out.brief, source_url: out.source_url }));
      router.push("/ad-clone?from=tracked");
    } catch (err) {
      setError(errorMessage(err));
      setBusy("");
    }
  };

  const dismiss = async () => {
    try {
      await dismissAlerts(await requestOptions());
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (!overview) {
    return error ? <ErrorText message={error} /> : <Loader2 className="size-5 animate-spin" aria-label="Loading" />;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Telescope className="size-6 text-primary" aria-hidden /> Competitor ads
        </h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Ads from the official Meta and TikTok ad libraries. The longer an ad runs, the more likely it works. Clone the
          structure of a winner for your own product.
        </p>
      </div>

      <ul className="grid gap-3 sm:grid-cols-2" aria-label="Ad library sources">
        {overview.sources.map((s) => (
          <li key={s.id} className="glass-subtle rounded-2xl p-4 text-sm">
            <p className="flex items-center gap-2 font-medium">
              <span
                className={cn("size-2 rounded-full", s.connected ? "bg-success" : "bg-muted-foreground/50")}
                aria-hidden
              />
              {s.name}: {s.connected ? "connected" : "not connected yet"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{s.detail}</p>
          </li>
        ))}
      </ul>

      {overview.alerts > 0 ? (
        <div className="glass-subtle flex items-center justify-between gap-3 rounded-2xl p-4" role="status">
          <p className="flex items-center gap-2 text-sm">
            <Bell className="size-4 text-primary" aria-hidden /> {overview.alerts} new ads since the last check
          </p>
          <Button size="sm" variant="ghost" onClick={() => void dismiss()}>
            Dismiss
          </Button>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <div className="space-y-4">
          <ul className="space-y-2" aria-label="Tracked brands">
            {overview.brands.map((b) => (
              <li key={b.id} className="glass-subtle flex items-center justify-between gap-2 rounded-2xl p-3 text-sm">
                <div>
                  <p className="font-medium">{b.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {b.ads} ads, {b.winners} winners{b.new ? `, ${b.new} new` : ""}
                  </p>
                  {b.last_error ? <p className="text-xs text-muted-foreground">{b.last_error}</p> : null}
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => void refresh(b.id)}
                  disabled={busy === b.id}
                  aria-label={`Refresh ${b.name}`}
                >
                  {busy === b.id ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
                </Button>
              </li>
            ))}
          </ul>
          <AddBrandForm onAdded={() => void load()} />
        </div>

        <div className="space-y-4">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by tier">
            {TIERS.map((t) => (
              <button
                key={t.id || "all"}
                type="button"
                aria-pressed={tier === t.id}
                onClick={() => setTier(t.id)}
                className={cn(
                  "glass-subtle rounded-full px-3 py-1.5 text-xs",
                  tier === t.id && "border-primary/70 font-medium text-primary",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          {note ? <p className="text-sm text-muted-foreground" role="status">{note}</p> : null}
          {error ? <ErrorText message={error} /> : null}
          {ads.length ? (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {ads.map((ad) => (
                <AdCard key={ad.id} ad={ad} onClone={(a) => void clone(a)} busy={busy !== ""} />
              ))}
            </div>
          ) : (
            <p className="glass-subtle rounded-2xl p-6 text-sm text-muted-foreground">
              No ads yet. Track a brand and refresh it.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
