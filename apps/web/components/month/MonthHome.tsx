"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Globe, Loader2, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorText, errorMessage, formatDate, useRequestOptions } from "@/components/design/shared";

import { createPlan, deletePlan, listPlans } from "./api";
import type { MonthPlanSummary } from "./types";

const STEPS = ["Reading your website", "Finding your audience", "Matching viral formats", "Writing 30 posts"];

function Working() {
  const [step, setStep] = React.useState(0);
  React.useEffect(() => {
    const t = window.setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 6000);
    return () => window.clearInterval(t);
  }, []);
  return (
    <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground" aria-live="polite">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {STEPS[step]}…
    </p>
  );
}

/** One input: your website. Out: a month of posts to swipe through. */
export function MonthHome({ initialUrl = "" }: { initialUrl?: string }) {
  const router = useRouter();
  const getOptions = useRequestOptions();
  const [url, setUrl] = React.useState(initialUrl);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [plans, setPlans] = React.useState<MonthPlanSummary[] | null>(null);

  React.useEffect(() => {
    let alive = true;
    getOptions()
      .then((opts) => listPlans(opts))
      .then((r) => alive && setPlans(r.plans))
      .catch(() => alive && setPlans([]));
    return () => {
      alive = false;
    };
  }, [getOptions]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const plan = await createPlan(url.trim(), await getOptions());
      router.push(`/month/${encodeURIComponent(plan.id)}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await deletePlan(id, await getOptions());
      setPlans((p) => (p ? p.filter((x) => x.id !== id) : p));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="space-y-10">
      <form onSubmit={submit} className="mx-auto max-w-xl space-y-3">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Globe className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="yourwebsite.com"
              aria-label="Your website"
              className="h-12 pl-9 text-base"
              autoFocus
              disabled={busy}
              inputMode="url"
            />
          </div>
          <Button type="submit" size="lg" disabled={busy || !url.trim()}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowRight aria-hidden />}
            Make my month
          </Button>
        </div>
        {busy ? <Working /> : null}
        <ErrorText message={error} />
      </form>

      {plans && plans.length ? (
        <div className="mx-auto max-w-xl space-y-2">
          <h2 className="text-sm font-semibold text-muted-foreground">Your plans</h2>
          {plans.map((p) => (
            <Card key={p.id}>
              <CardContent className="flex items-center justify-between gap-3 p-3">
                <Link href={`/month/${encodeURIComponent(p.id)}`} className="min-w-0 flex-1">
                  <p className="truncate font-medium">{p.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatDate(p.created_at)} · {p.counts.kept} kept · {p.counts.pending} to swipe
                  </p>
                </Link>
                <Button type="button" size="icon" variant="ghost" aria-label={`Delete ${p.name}`} title="Delete"
                        onClick={() => remove(p.id)}>
                  <Trash2 aria-hidden />
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}
    </div>
  );
}
