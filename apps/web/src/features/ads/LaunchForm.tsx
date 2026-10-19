"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Rocket } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { getAdProject, listAdProjects, type ProjectDetail, type ProjectSummary } from "@/src/features/ad-studio/api";
import { ChipToggle, ErrorText, LoadError, errorMessage, toggleIn, useRequestOptions } from "@/src/features/ad-studio/shared";
import {
  CTAS,
  getAdsGate,
  getConnection,
  launchCampaign,
  type AdsGate,
  type AdsPlatform,
  type Audience,
  type Connection,
  type OptimizeFor,
} from "./api";
import { AudienceFields, DEFAULT_AUDIENCE } from "./AudienceFields";
import { CreativePicker } from "./CreativePicker";
import { formatMinor, toMinor } from "./format";
import { GateNotice } from "./GateNotice";

interface Loaded {
  gate: AdsGate;
  projects: ProjectSummary[];
  connections: Partial<Record<AdsPlatform, Connection>>;
}

/** Launch a paid campaign from finished Ad Studio variants. */
export function LaunchForm({ initialProjectId }: { initialProjectId?: string }) {
  const router = useRouter();
  const requestOptions = useRequestOptions();
  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  const [error, setError] = React.useState("");
  const [loadFailure, setLoadFailure] = React.useState<unknown>(null);
  const [attempt, setAttempt] = React.useState(0);
  const [projectId, setProjectId] = React.useState(initialProjectId || "");
  const [project, setProject] = React.useState<ProjectDetail | null>(null);
  const [platform, setPlatform] = React.useState<AdsPlatform | "">("");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [budget, setBudget] = React.useState("");
  const [audience, setAudience] = React.useState<Audience>(DEFAULT_AUDIENCE);
  const [countriesText, setCountriesText] = React.useState("US");
  const [landingUrl, setLandingUrl] = React.useState("");
  const [name, setName] = React.useState("");
  const [cta, setCta] = React.useState<string>("SHOP_NOW");
  const [optimizeFor, setOptimizeFor] = React.useState<OptimizeFor>("ctr");
  const [autoOptimize, setAutoOptimize] = React.useState(true);
  const [startNow, setStartNow] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const opts = await requestOptions();
        const [gate, list] = await Promise.all([getAdsGate(opts), listAdProjects(opts)]);
        const enabled = gate.platforms.filter((p) => p.enabled).map((p) => p.platform);
        const conns = await Promise.all(enabled.map((p) => getConnection(p, opts)));
        const connections = Object.fromEntries(conns.map((c) => [c.platform, c]));
        if (cancelled) return;
        setLoaded({ gate, projects: list.projects, connections });
        setLoadFailure(null);
        const firstReady = conns.find((c) => c.ready);
        if (firstReady) setPlatform(firstReady.platform);
      } catch (err) {
        if (!cancelled) setLoadFailure(err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [requestOptions, attempt]);

  React.useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    (async () => {
      try {
        const detail = await getAdProject(projectId, await requestOptions());
        if (cancelled) return;
        setProject(detail);
        setSelected([]);
        setLandingUrl(detail.source_url || "");
        setName(`Menivor - ${detail.title}`.slice(0, 200));
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, requestOptions]);

  if (!loaded && !loadFailure) return <Skeleton className="h-96" />;
  if (!loaded) {
    return (
      <LoadError
        error={loadFailure}
        onRetry={() => {
          setLoadFailure(null);
          setAttempt((n) => n + 1);
        }}
        fallback="We couldn't load your ad setup. Please try again."
      />
    );
  }
  if (!loaded.gate.enabled) return <GateNotice gate={loaded.gate} />;

  const gate = loaded.gate.platforms.find((p) => p.platform === platform);
  const conn = platform ? loaded.connections[platform] : undefined;
  const currency = conn?.currency || "USD";
  const minTotal = (gate?.min_daily_budget_minor ?? 0) * Math.max(1, selected.length);
  const budgetMinor = toMinor(Number.parseFloat(budget) || 0, currency);
  const readyPlatforms = loaded.gate.platforms.filter((p) => p.enabled && loaded.connections[p.platform]?.ready);
  const canSubmit =
    !busy && !!project && !!platform && !!conn?.ready && selected.length > 0 && budgetMinor >= minTotal &&
    audience.countries.length > 0 && audience.age_min <= audience.age_max && landingUrl.startsWith("https://");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || !platform || !project) return;
    setBusy(true);
    setError("");
    try {
      const campaign = await launchCampaign(
        {
          project_id: project.id, platform, variant_ids: selected, daily_budget_minor: budgetMinor, audience,
          name, landing_url: landingUrl, cta, optimize_for: optimizeFor, auto_optimize: autoOptimize, start_now: startNow,
        },
        await requestOptions(),
      );
      router.push(`/ads/${campaign.key}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-8">
      {readyPlatforms.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Connect an ad account and choose its page or identity on the <Link className="text-primary underline" href="/ads">paid ads page</Link> first.
        </p>
      ) : null}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">1. Ads to run</h2>
        <div className="max-w-md space-y-1">
          <Label htmlFor="ads-project">Ad Studio project</Label>
          <Select id="ads-project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">Choose a project</option>
            {loaded.projects.map((p) => (
              <option key={p.id} value={p.id} disabled={p.done_count === 0}>
                {p.title} ({p.done_count} ready)
              </option>
            ))}
          </Select>
        </div>
        {project ? (
          <CreativePicker variants={project.variants} selected={selected} onToggle={(id) => setSelected((s) => toggleIn(s, id))} />
        ) : null}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">2. Where and how much</h2>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Platform">
          {readyPlatforms.map((p) => (
            <ChipToggle key={p.platform} selected={platform === p.platform} onToggle={() => setPlatform(p.platform)}>
              {p.label}
            </ChipToggle>
          ))}
        </div>
        <div className="grid max-w-2xl gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="ads-budget">Daily budget ({currency})</Label>
            <Input id="ads-budget" type="number" min={0} step="0.01" value={budget} onChange={(e) => setBudget(e.target.value)} />
            {gate ? (
              <p className="text-xs text-muted-foreground">
                At least {formatMinor(minTotal, currency)} per day: the platform minimum per ad times {Math.max(1, selected.length)} ads.
              </p>
            ) : null}
          </div>
          <div className="space-y-1">
            <Label htmlFor="ads-name">Campaign name</Label>
            <Input id="ads-name" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ads-landing">Landing page</Label>
            <Input id="ads-landing" type="url" placeholder="https://" value={landingUrl} onChange={(e) => setLandingUrl(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ads-cta">Button</Label>
            <Select id="ads-cta" value={cta} onChange={(e) => setCta(e.target.value)}>
              {CTAS.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <div className="max-w-2xl">
          <AudienceFields audience={audience} countriesText={countriesText} onCountriesText={setCountriesText} onChange={setAudience} />
        </div>
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">3. Winner loop</h2>
        <div className="max-w-md space-y-1">
          <Label htmlFor="ads-optimize">Give more budget to the ads with the best</Label>
          <Select id="ads-optimize" value={optimizeFor} onChange={(e) => setOptimizeFor(e.target.value as OptimizeFor)}>
            <option value="ctr">Click-through rate</option>
            <option value="leads">Lead rate (needs lead events from your pixel)</option>
          </Select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={autoOptimize} onChange={(e) => setAutoOptimize(e.target.checked)} />
          Re-split the budget automatically once a day
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={startNow} onChange={(e) => setStartNow(e.target.checked)} />
          Start spending as soon as the ads are approved (otherwise the campaign is created paused)
        </label>
      </section>
      <ErrorText message={error} />
      <Button type="submit" disabled={!canSubmit}>
        <Rocket className="mr-2 h-4 w-4" aria-hidden /> {busy ? "Creating campaign" : "Create campaign"}
      </Button>
    </form>
  );
}
