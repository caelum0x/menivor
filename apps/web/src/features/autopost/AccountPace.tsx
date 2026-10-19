"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

import {
  disconnectAccount,
  listAccounts,
  listProviders,
  updateAccount,
  type Account,
  type ProviderState,
} from "./api";
import { PROVIDER_LABEL } from "./plan";

/** Parse "9-12, 18" into [9, 10, 11, 12, 18]. Throws on anything outside 0-23. */
export function parseHours(raw: string): number[] {
  const hours = new Set<number>();
  for (const part of raw.split(",").map((p) => p.trim()).filter(Boolean)) {
    const [first, second] = part.split("-").map((x) => Number(x.trim()));
    const start = first ?? Number.NaN;
    const end = second ?? start;
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end > 23 || start > end) {
      throw new Error("Use hours from 0 to 23, like 9-12, 18.");
    }
    for (let h = start; h <= end; h += 1) hours.add(h);
  }
  return Array.from(hours).sort((x, y) => x - y);
}

export function formatHours(hours: number[]): string {
  const parts: string[] = [];
  let start: number | null = null;
  let prev = Number.NaN;
  for (const h of [...hours, Number.NaN]) {
    if (start !== null && h === prev + 1) {
      prev = h;
      continue;
    }
    if (start !== null) parts.push(start === prev ? String(start) : `${start}-${prev}`);
    start = Number.isNaN(h) ? null : h;
    prev = h;
  }
  return parts.join(", ");
}

/** One account's posting pace. One action: save. */
export function AccountPace({ accountId }: { accountId: string }) {
  const router = useRouter();
  const [account, setAccount] = React.useState<Account | null>(null);
  const [limits, setLimits] = React.useState<ProviderState | null>(null);
  const [cap, setCap] = React.useState("");
  const [gap, setGap] = React.useState("");
  const [hours, setHours] = React.useState("");
  const [tz, setTz] = React.useState("UTC");
  const [message, setMessage] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const [a, p] = await Promise.all([listAccounts(), listProviders()]);
        const found = a.accounts.find((x) => x.id === accountId) ?? null;
        if (!live) return;
        setAccount(found);
        if (found) {
          setLimits(p.providers.find((x) => x.provider === found.provider) ?? null);
          setCap(String(found.daily_cap));
          setGap(String(found.min_gap_minutes));
          setHours(formatHours(found.posting_hours));
          setTz(found.timezone || "UTC");
        } else {
          setMessage("This account was not found.");
        }
      } catch (err) {
        if (live) setMessage(friendlyErrorMessage(err, "Could not load this account."));
      }
    })();
    return () => {
      live = false;
    };
  }, [accountId]);

  if (!account) {
    return <p className="text-sm text-muted-foreground">{message || "Loading"}</p>;
  }

  const save = async () => {
    setBusy(true);
    setMessage("");
    try {
      const updated = await updateAccount(account.id, {
        daily_cap: Number(cap),
        min_gap_minutes: Number(gap),
        posting_hours: parseHours(hours),
        timezone: tz.trim() || "UTC",
      });
      setAccount(updated);
      setMessage("Saved.");
    } catch (err) {
      setMessage(err instanceof Error && !("status" in err) ? err.message : friendlyErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const togglePause = async () => {
    setBusy(true);
    try {
      setAccount(await updateAccount(account.id, { paused: account.status !== "paused" }));
    } catch (err) {
      setMessage(friendlyErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    if (!window.confirm("Disconnect this account? Posts that have not gone out are canceled.")) return;
    setBusy(true);
    try {
      await disconnectAccount(account.id);
      router.push("/autopost/accounts");
    } catch (err) {
      setMessage(friendlyErrorMessage(err));
      setBusy(false);
    }
  };

  const name = account.display_name || account.handle || PROVIDER_LABEL[account.provider];
  return (
    <Card>
      <CardContent className="space-y-5 p-6">
        <div>
          <h2 className="text-lg font-semibold">{name}</h2>
          <p className="text-sm text-muted-foreground">
            {PROVIDER_LABEL[account.provider]} · {account.posts_last_24h} posts in the last day
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="cap">Posts per day</Label>
            <Input id="cap" type="number" min={1} max={limits?.daily_cap_max ?? 15} value={cap}
              onChange={(e) => setCap(e.target.value)} />
            <p className="text-xs text-muted-foreground">Up to {limits?.daily_cap_max ?? "the platform limit"}.</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gap">Minutes between posts</Label>
            <Input id="gap" type="number" min={limits?.min_gap_floor_minutes ?? 15} value={gap}
              onChange={(e) => setGap(e.target.value)} />
            <p className="text-xs text-muted-foreground">At least {limits?.min_gap_floor_minutes ?? 15}.</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="hours">Posting hours</Label>
            <Input id="hours" placeholder="Any time, or like 9-12, 18-21" value={hours}
              onChange={(e) => setHours(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tz">Time zone</Label>
            <Input id="tz" placeholder="Europe/Istanbul" value={tz} onChange={(e) => setTz(e.target.value)} />
          </div>
        </div>
        {message ? <p role="status" className="text-sm">{message}</p> : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void save()} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}
            Save pace
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void togglePause()} disabled={busy}>
            {account.status === "paused" ? "Resume posting" : "Pause posting"}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void disconnect()} disabled={busy}>
            Disconnect
          </Button>
          <Link href="/autopost/accounts" className="ml-auto text-sm text-muted-foreground hover:underline">
            Back to accounts
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
