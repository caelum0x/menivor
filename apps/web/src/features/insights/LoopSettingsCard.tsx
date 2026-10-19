"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, Save, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { platformLabel } from "./format";
import {
  LOOP_PLATFORMS,
  type LoopConfigInput,
  type LoopDetail,
  type LoopMode,
  type LoopPlatform,
} from "./types";

const MODE_OPTIONS: readonly { value: LoopMode; label: string; hint: string }[] = [
  { value: "off", label: "Off", hint: "Nothing is posted or remade." },
  {
    value: "manual",
    label: "Manual",
    hint: "Posts and measures automatically; you click Remake winner.",
  },
  {
    value: "auto",
    label: "Auto",
    hint: "Remakes a clear winner automatically, within your spend cap.",
  },
];

const WINDOW_OPTIONS = [24, 48, 72, 96, 168] as const;

export interface LoopSettingsCardProps {
  detail: LoopDetail;
  saving: boolean;
  onSave: (input: LoopConfigInput) => void;
}

/** Per-project loop setting: mode, auto-publish platforms, spend cap and window. */
export function LoopSettingsCard({ detail, saving, onSave }: Readonly<LoopSettingsCardProps>) {
  const [mode, setMode] = React.useState<LoopMode>(detail.configured ? detail.mode : "manual");
  const [platforms, setPlatforms] = React.useState<LoopPlatform[]>(detail.platforms);
  const [cap, setCap] = React.useState<string>(
    String(detail.configured ? detail.spend_cap_credits : detail.remake_cost_credits * 2),
  );
  const [windowHours, setWindowHours] = React.useState<number>(detail.check_after_hours ?? 48);
  const [minViews, setMinViews] = React.useState<string>(String(detail.min_views ?? 100));

  React.useEffect(() => {
    setMode(detail.configured ? detail.mode : "manual");
    setPlatforms(detail.platforms);
    setCap(String(detail.configured ? detail.spend_cap_credits : detail.remake_cost_credits * 2));
    setWindowHours(detail.check_after_hours ?? 48);
    setMinViews(String(detail.min_views ?? 100));
  }, [detail]);

  const capNumber = Number.parseInt(cap, 10);
  const minViewsNumber = Number.parseInt(minViews, 10);
  const capValid = Number.isFinite(capNumber) && capNumber >= 0 && capNumber <= 1000;
  const minViewsValid =
    Number.isFinite(minViewsNumber) && minViewsNumber >= 0 && minViewsNumber <= 100000;
  const spentPct =
    detail.spend_cap_credits > 0
      ? Math.min(100, (detail.spent_credits / detail.spend_cap_credits) * 100)
      : 0;

  const togglePlatform = (platform: LoopPlatform) =>
    setPlatforms((current) =>
      current.includes(platform)
        ? current.filter((p) => p !== platform)
        : [...current, platform],
    );

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!capValid || !minViewsValid) return;
    onSave({
      mode,
      platforms: mode === "off" ? [] : platforms,
      spend_cap_credits: capNumber,
      check_after_hours: windowHours,
      min_views: minViewsNumber,
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Settings2 className="size-4" aria-hidden /> Loop settings
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form className="space-y-5" onSubmit={submit}>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Mode</legend>
            <div role="radiogroup" className="grid grid-cols-3 gap-2">
              {MODE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={mode === option.value}
                  onClick={() => setMode(option.value)}
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm font-medium transition-colors",
                    mode === option.value
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border text-muted-foreground hover:bg-secondary/40",
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {MODE_OPTIONS.find((o) => o.value === mode)?.hint}
            </p>
          </fieldset>

          {mode !== "off" && (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Auto-publish to</legend>
              {!detail.publishing_enabled && (
                <p className="flex items-start gap-2 rounded-md border border-border bg-secondary/30 p-2 text-xs text-muted-foreground">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  Direct publishing is not enabled yet. Leave these unchecked, post the variants
                  yourself and log their results on each reel; the loop ranks them from those numbers.
                </p>
              )}
              <div className="flex flex-wrap gap-3">
                {LOOP_PLATFORMS.map((platform) => (
                  <label key={platform} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      checked={platforms.includes(platform)}
                      disabled={!detail.publishing_enabled}
                      onChange={() => togglePlatform(platform)}
                    />
                    {platformLabel(platform)}
                  </label>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                Uses your connected accounts (
                <Link href="/connections" className="underline underline-offset-2">
                  manage connections
                </Link>
                ). Variants are posted at spaced times so they do not compete with each other.
                Reading results needs analytics permission on each account.
              </p>
            </fieldset>
          )}

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="loop-cap">Spend cap (credits)</Label>
              <Input
                id="loop-cap"
                type="number"
                min={0}
                max={1000}
                inputMode="numeric"
                value={cap}
                onChange={(e) => setCap(e.target.value)}
                aria-invalid={!capValid}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="loop-window">Read results after</Label>
              <Select
                id="loop-window"
                value={String(windowHours)}
                onChange={(e) => setWindowHours(Number(e.target.value))}
              >
                {WINDOW_OPTIONS.map((h) => (
                  <option key={h} value={h}>
                    {h < 168 ? `${h} hours` : "7 days"}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="loop-min-views">Min views per variant</Label>
              <Input
                id="loop-min-views"
                type="number"
                min={0}
                max={100000}
                inputMode="numeric"
                value={minViews}
                onChange={(e) => setMinViews(e.target.value)}
                aria-invalid={!minViewsValid}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>
                {detail.spent_credits} of {detail.spend_cap_credits} credits spent on remakes
              </span>
              <span>{detail.remake_cost_credits} credits per remake</span>
            </div>
            <Progress value={spentPct} aria-label="Remake spend against cap" />
          </div>

          <Button type="submit" disabled={saving || !capValid || !minViewsValid}>
            <Save aria-hidden /> {saving ? "Saving" : detail.configured ? "Save settings" : "Start loop"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
