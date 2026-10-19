"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { BarChart3, FlaskConical, Loader2, Plus, Trophy } from "lucide-react";

import { readableApiError } from "@/src/shared/launch-gate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  createExperiment,
  getExperiment,
  type Experiment,
} from "./api";

/** Create 1-body/N-hooks retention experiments and read their per-hook metrics. */
export function Experiments() {
  const { getToken } = useAuth();
  const [experimentKey, setExperimentKey] = React.useState("");
  const [bodyRef, setBodyRef] = React.useState("");
  const [hookRefs, setHookRefs] = React.useState<string[]>(["", ""]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const [lookupKey, setLookupKey] = React.useState("");
  const [experiment, setExperiment] = React.useState<Experiment | null>(null);
  const [metricsLoading, setMetricsLoading] = React.useState(false);
  const [metricsError, setMetricsError] = React.useState("");

  const updateHook = React.useCallback((index: number, value: string) => {
    setHookRefs((prev) => prev.map((h, i) => (i === index ? value : h)));
  }, []);

  const addHook = React.useCallback(() => {
    setHookRefs((prev) => [...prev, ""]);
  }, []);

  const onCreate = React.useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const refs = hookRefs.map((h) => h.trim()).filter(Boolean);
      const res = await createExperiment(
        {
          experiment_key: experimentKey.trim(),
          hook_refs: refs,
          body_ref: bodyRef.trim() || undefined,
        },
        { token, idempotencyKey: crypto.randomUUID() },
      );
      setLookupKey(res.experiment_key);
      setExperiment(null);
      setMetricsError("");
    } catch (err) {
      setError(
        readableApiError(err, "Failed to create experiment."),
      );
    } finally {
      setBusy(false);
    }
  }, [getToken, experimentKey, bodyRef, hookRefs]);

  const onLoadMetrics = React.useCallback(async () => {
    setMetricsLoading(true);
    setMetricsError("");
    setExperiment(null);
    try {
      const token = (await getToken()) ?? undefined;
      const res = await getExperiment(lookupKey.trim(), { token });
      setExperiment(res);
    } catch (err) {
      setMetricsError(
        readableApiError(err, "Failed to load metrics."),
      );
    } finally {
      setMetricsLoading(false);
    }
  }, [getToken, lookupKey]);

  const filledHooks = hookRefs.filter((h) => h.trim()).length;
  const canCreate = !busy && experimentKey.trim() !== "" && filledHooks >= 2;

  return (
    <Card>
      <CardContent className="space-y-5 py-5">
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-primary" aria-hidden />
          <h2 className="font-semibold">Hook retention A/B test</h2>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="exp-key">Experiment key</Label>
          <Input
            id="exp-key"
            placeholder="my-launch-hooks"
            value={experimentKey}
            onChange={(e) => setExperimentKey(e.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="exp-body">Body ref (optional)</Label>
          <Input
            id="exp-body"
            placeholder="Shared body clip ref"
            value={bodyRef}
            onChange={(e) => setBodyRef(e.target.value)}
          />
        </div>

        <div className="space-y-3">
          {hookRefs.map((h, i) => (
            <div key={i} className="space-y-1.5">
              <Input
                aria-label={`Hook ${String.fromCharCode(65 + i)} ref`}
                placeholder={`Hook ${String.fromCharCode(65 + i)} ref`}
                value={h}
                onChange={(e) => updateHook(i, e.target.value)}
              />
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addHook} type="button">
            <Plus className="mr-1 h-4 w-4" aria-hidden /> Add hook
          </Button>
        </div>

        <Button onClick={() => void onCreate()} disabled={!canCreate}>
          {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
          Create experiment
        </Button>
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}

        <div className="space-y-2 border-t border-border pt-4">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-primary" aria-hidden />
            <h3 className="text-sm font-semibold">Results</h3>
          </div>
          <div className="flex gap-2">
            <Input
              aria-label="Experiment key"
              placeholder="Experiment key"
              value={lookupKey}
              onChange={(e) => setLookupKey(e.target.value)}
            />
            <Button
              variant="secondary"
              onClick={() => void onLoadMetrics()}
              disabled={metricsLoading || lookupKey.trim() === ""}
            >
              {metricsLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                "Load metrics"
              )}
            </Button>
          </div>

          {metricsError && (
            <p className="text-sm text-destructive" role="alert">
              {metricsError}
            </p>
          )}
          {experiment && experiment.variants.length === 0 && (
            <p className="text-sm text-muted-foreground">No hook variants yet.</p>
          )}
          {experiment && experiment.variants.length > 0 && (
            <div className="space-y-2">
              {experiment.variants.map((v) => (
                <div
                  key={v.id}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">{v.hook_ref || v.id}</p>
                    <p className="text-xs text-muted-foreground">
                      {v.views.toLocaleString()} views ·{" "}
                      {Math.round(v.completion_rate * 100)}% completion ·{" "}
                      {Math.round(v.avg_watch_frac * 100)}% avg watch
                    </p>
                  </div>
                  {experiment.winner_variant_id === v.id && (
                    <Badge variant="success">
                      <Trophy className="mr-1 h-3 w-3" aria-hidden /> Winner
                    </Badge>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
