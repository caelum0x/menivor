"use client";

import * as React from "react";
import Link from "next/link";
import { CalendarClock, ClipboardList, Loader2, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { AdVariant } from "./api";
import { PLATFORM_LABEL, type TestPlatform, type TestsPayload, type StartTestInput } from "./publish-api";
import { ChipToggle, ErrorText, errorMessage, toggleIn } from "./shared";

/**
 * "Publish and test": pick 2-6 finished ads and the connected accounts, then one
 * click schedules them (spaced under each platform's daily cap) and opens the
 * 48h winner loop. When direct publishing is unavailable the same test runs
 * manually: the creator posts the downloads and logs each ad's numbers.
 */
export function PublishTestPanel({
  payload,
  variants,
  onStart,
}: {
  payload: TestsPayload;
  variants: AdVariant[];
  onStart: (input: StartTestInput) => Promise<string>;
}) {
  const { readiness, eligible_variant_ids: eligibleIds, min_ads: minAds, max_ads: maxAds } = payload;
  const eligible = React.useMemo(
    () => variants.filter((v) => eligibleIds.includes(v.id)),
    [variants, eligibleIds],
  );
  const connected = readiness.platforms.filter((p) => p.connected).map((p) => p.platform);
  const [selected, setSelected] = React.useState<string[]>([]);
  const [platforms, setPlatforms] = React.useState<TestPlatform[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [note, setNote] = React.useState("");

  // Default: every eligible ad (up to the cap) and every connected account.
  const eligibleKey = eligibleIds.join(",");
  React.useEffect(() => {
    setSelected(eligibleKey ? eligibleKey.split(",").slice(0, maxAds) : []);
  }, [eligibleKey, maxAds]);
  const connectedKey = connected.join(",");
  React.useEffect(() => {
    setPlatforms(connectedKey ? (connectedKey.split(",") as TestPlatform[]) : []);
  }, [connectedKey]);

  const count = selected.length;
  const countOk = count >= minAds && count <= maxAds;
  const canPublish = readiness.can_publish && platforms.length > 0 && countOk;
  const slowest = readiness.platforms
    .filter((p) => platforms.includes(p.platform))
    .map((p) => ({ ...p, days: Math.max(1, Math.ceil(count / p.daily_cap)) }))
    .sort((a, b) => b.days - a.days)[0];

  const start = async (mode: StartTestInput["mode"]) => {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const loopNote = await onStart({ mode, platforms: mode === "publish" ? platforms : [], variant_ids: selected });
      setNote(
        loopNote ||
          (mode === "publish"
            ? "Scheduled. Posts go out on your accounts at the times shown below."
            : "Test started. Post the ads yourself, then log each ad's numbers below."),
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (eligible.length < minAds) {
    return (
      <Card>
        <CardContent className="space-y-1 p-4">
          <p className="font-medium">Publish and test</p>
          <p className="text-sm text-muted-foreground">
            Render at least {minAds} ads that are not already in a test. Then publish them in one click and
            the one that holds viewers best is picked 48 hours after the last post goes live.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div>
          <p className="font-medium">Publish and test</p>
          <p className="text-sm text-muted-foreground">
            Posts each ad to your own accounts, spaced so they do not compete, then compares real numbers 48
            hours after the last one goes live. Publishing is free; nothing is charged.
          </p>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">
            Ads in this test ({count} of {minAds}-{maxAds})
          </legend>
          <div className="flex flex-wrap gap-2">
            {eligible.map((ad) => (
              <ChipToggle
                key={ad.id}
                selected={selected.includes(ad.id)}
                onToggle={() => setSelected((s) => toggleIn(s, ad.id))}
                disabled={busy || (!selected.includes(ad.id) && count >= maxAds)}
                title={ad.hook || ad.script}
              >
                {ad.angle_label} · {ad.format_label} · {ad.aspect}
              </ChipToggle>
            ))}
          </div>
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Post to</legend>
          <div className="flex flex-wrap items-center gap-2">
            {readiness.platforms.map((p) => (
              <ChipToggle
                key={p.platform}
                selected={platforms.includes(p.platform)}
                onToggle={() => setPlatforms((s) => toggleIn(s, p.platform))}
                disabled={busy || !p.connected || !readiness.publishing.enabled}
                title={p.connected ? `Up to ${p.daily_cap} posts a day` : `${p.label} is not connected`}
              >
                {PLATFORM_LABEL[p.platform]}
                {p.connected ? "" : " (not connected)"}
              </ChipToggle>
            ))}
            {readiness.platforms.some((p) => !p.connected) ? (
              <Link href="/connections" className="text-sm text-primary underline-offset-4 hover:underline">
                Connect accounts
              </Link>
            ) : null}
          </div>
          {slowest && count > slowest.daily_cap ? (
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <CalendarClock className="h-3.5 w-3.5" aria-hidden />
              {PLATFORM_LABEL[slowest.platform]} allows {slowest.daily_cap} posts a day, so {count} ads go out over{" "}
              {slowest.days} days.
            </p>
          ) : null}
          {selected.some((id) => eligible.find((v) => v.id === id)?.aspect !== "9:16") && platforms.length ? (
            <p className="text-xs text-muted-foreground">Square and landscape ads post as-is; 9:16 usually reaches further.</p>
          ) : null}
        </fieldset>

        {readiness.blocker ? (
          <p className="rounded-md border border-border bg-secondary/40 p-3 text-sm text-muted-foreground" role="status">
            {readiness.blocker}
            {readiness.pro.status === "required" ? (
              <>
                {" "}
                <Link href="/billing" className="text-primary underline-offset-4 hover:underline">
                  See plans
                </Link>
              </>
            ) : null}
          </p>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void start("publish")} disabled={busy || !canPublish}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Send aria-hidden />} Publish and test
          </Button>
          <Button variant="outline" onClick={() => void start("manual")} disabled={busy || !countOk}>
            <ClipboardList aria-hidden /> I will post them myself
          </Button>
        </div>
        {note ? <p className="text-sm text-muted-foreground" role="status">{note}</p> : null}
        <ErrorText message={error} />
      </CardContent>
    </Card>
  );
}
