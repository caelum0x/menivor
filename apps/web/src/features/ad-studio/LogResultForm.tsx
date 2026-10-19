"use client";

import * as React from "react";
import { Loader2, Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { LoggedResult, LogResultInput } from "./publish-api";
import { ErrorText, errorMessage } from "./shared";

const PLATFORMS = [
  { id: "tiktok", label: "TikTok" },
  { id: "instagram", label: "Instagram" },
  { id: "youtube", label: "YouTube" },
  { id: "other", label: "Other" },
];

function whole(value: string): number | undefined {
  const n = Number(value);
  return value.trim() === "" || !Number.isFinite(n) || n < 0 ? undefined : Math.floor(n);
}

/** Manual tests: the creator types what one ad earned on the platform it was posted to. */
export function LogResultForm({
  initial,
  onSubmit,
}: {
  initial: LoggedResult | null;
  onSubmit: (input: LogResultInput) => Promise<void>;
}) {
  const [platform, setPlatform] = React.useState(initial?.platform || "tiktok");
  const [views, setViews] = React.useState(initial ? String(initial.views) : "");
  const [likes, setLikes] = React.useState(initial ? String(initial.likes) : "");
  const [comments, setComments] = React.useState(initial ? String(initial.comments) : "");
  const [shares, setShares] = React.useState(initial ? String(initial.shares) : "");
  const [retention, setRetention] = React.useState(initial?.retention_pct ? String(initial.retention_pct) : "");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [saved, setSaved] = React.useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const viewCount = whole(views);
    if (viewCount === undefined) {
      setError("Enter the view count.");
      return;
    }
    const retentionPct = retention.trim() === "" ? undefined : Number(retention);
    if (retentionPct !== undefined && (!Number.isFinite(retentionPct) || retentionPct < 0 || retentionPct > 100)) {
      setError("Average watched must be between 0 and 100.");
      return;
    }
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      await onSubmit({
        platform,
        views: viewCount,
        likes: whole(likes),
        comments: whole(comments),
        shares: whole(shares),
        retention_pct: retentionPct,
      });
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const field = (label: string, value: string, set: (v: string) => void, required = false) => (
    <label className="space-y-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <Input inputMode="numeric" value={value} onChange={(e) => set(e.target.value)} required={required} className="h-8 w-24" />
    </label>
  );

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2 border-t border-border pt-2" aria-label="Log this ad's results">
      <label className="space-y-1 text-xs">
        <span className="text-muted-foreground">Posted on</span>
        <select
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
          className="h-8 rounded-md border border-border bg-background px-2 text-sm"
        >
          {PLATFORMS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
      </label>
      {field("Views", views, setViews, true)}
      {field("Likes", likes, setLikes)}
      {field("Comments", comments, setComments)}
      {field("Shares", shares, setShares)}
      {field("Avg. watched %", retention, setRetention)}
      <Button type="submit" size="sm" variant="outline" disabled={busy}>
        {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />} {initial ? "Update" : "Log results"}
      </Button>
      {saved ? <span className="text-xs text-muted-foreground" role="status">Saved.</span> : null}
      <ErrorText message={error} />
    </form>
  );
}
