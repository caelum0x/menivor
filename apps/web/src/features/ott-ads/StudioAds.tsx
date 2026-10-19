"use client";

import * as React from "react";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { addSponsor, getStudioAds, putAdSettings, stopSponsor, type AdRule, type StudioAdsView } from "./api";

const RULES: readonly [AdRule, string][] = [
  ["ads_on_free", "Show ads on free titles"],
  ["ads_on_paid", "Show ads to paying members too"],
  ["house_ads", "Fill empty slots with Menivor ads"],
];

/** Ad rules and sponsor slots. A sponsor slot is one of my free titles played before others, skippable after 5 s. */
export function StudioAds({ titles }: Readonly<{ titles: readonly { id: string; title: string; access_tier: string }[] }>) {
  const getApiToken = useApiToken();
  const [view, setView] = React.useState<StudioAdsView | null>(null);
  const [form, setForm] = React.useState({ title_id: "", name: "", sponsor: "", click_url: "" });
  const [error, setError] = React.useState("");
  const free = titles.filter((t) => t.access_tier === "free");

  const load = React.useCallback(async () => {
    try {
      setView(await getStudioAds({ token: await getApiToken() }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "Ads could not load."));
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (!view) return error ? <p role="alert" className="text-sm">{error}</p> : null;

  const toggle = async (rule: AdRule) => {
    try {
      setView(await putAdSettings({ [rule]: !view.settings[rule] }, { token: await getApiToken() }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "The ad rule could not be saved."));
    }
  };
  const add = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await addSponsor(form, { token: await getApiToken() });
      setForm({ title_id: "", name: "", sponsor: "", click_url: "" });
      setError("");
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "The sponsor slot could not be saved."));
    }
  };

  return (
    <section aria-label="Ads on my channel" className="space-y-3 rounded-xl border border-border p-3">
      <h2 className="text-sm font-semibold">Ads on my channel</h2>
      {RULES.map(([rule, label]) => (
        <label key={rule} className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={view.settings[rule]} onChange={() => void toggle(rule)} />
          {label}
        </label>
      ))}
      <form onSubmit={add} className="flex flex-wrap items-end gap-2 text-sm" aria-label="Add a sponsor slot">
        <label>
          Sponsor video
          <select className="ml-2 rounded border px-2 py-1" required value={form.title_id}
            onChange={(e) => setForm({ ...form, title_id: e.target.value })}>
            <option value="">Pick a free title</option>
            {free.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
          </select>
        </label>
        <label>Name<input className="ml-2 rounded border px-2 py-1" required value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Sponsor<input className="ml-2 rounded border px-2 py-1" value={form.sponsor}
          onChange={(e) => setForm({ ...form, sponsor: e.target.value })} /></label>
        <label>Link<input className="ml-2 rounded border px-2 py-1" type="url" value={form.click_url}
          onChange={(e) => setForm({ ...form, click_url: e.target.value })} /></label>
        <button type="submit" className="rounded-lg border px-3 py-1">Add sponsor slot</button>
      </form>
      <ul className="space-y-1 text-sm">
        {view.ads.map((ad) => (
          <li key={ad.id} data-ad={ad.id}>
            {ad.name}{ad.sponsor ? ` (${ad.sponsor})` : ""}: {ad.stats.impressions} views, {ad.stats.completes} watched to the end,{" "}
            {ad.stats.clicks} clicks {ad.active ? (
              <button type="button" className="underline" onClick={async () => {
                await stopSponsor(ad.id, { token: await getApiToken() }).catch(() => undefined);
                await load();
              }}>Stop</button>
            ) : "(stopped)"}
          </li>
        ))}
      </ul>
      {error ? <p role="alert" className="text-sm">{error}</p> : null}
    </section>
  );
}
