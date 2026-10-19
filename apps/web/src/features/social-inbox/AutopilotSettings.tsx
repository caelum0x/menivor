"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2, Play, Plug } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { RequestOptions } from "@/src/shared/api";
import {
  cleanError,
  getAutopilot,
  runAutopilot,
  updateAutopilot,
  type AutopilotOverview,
  type AutopilotPlatform,
  type AutopilotRules,
  type ReplyModeSetting,
  type RunSummary,
} from "./autopilot-api";
import { relativeTime } from "./format";

interface AutopilotSettingsProps {
  getOptions: () => Promise<RequestOptions>;
  onChanged: () => void;
}

function Toggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: Readonly<{ label: string; hint?: string; checked: boolean; disabled?: boolean; onChange: (v: boolean) => void }>) {
  const id = React.useId();
  return (
    <div className="flex items-start gap-3">
      <input
        id={id}
        type="checkbox"
        className="mt-1 size-4 accent-primary"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <label htmlFor={id} className="text-sm">
        <span className={disabled ? "text-muted-foreground" : undefined}>{label}</span>
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </label>
    </div>
  );
}

function summaryText(s: RunSummary): string {
  const parts = [
    s.liked && `${s.liked} liked`,
    s.hidden && `${s.hidden} hidden`,
    s.flagged && `${s.flagged} flagged`,
    s.leads && `${s.leads} sent to Leads`,
    s.replies_sent && `${s.replies_sent} replies sent`,
    s.drafts && `${s.drafts} drafts to approve`,
    s.skipped && `${s.skipped} skipped (daily limit)`,
    s.failed && `${s.failed} failed`,
  ].filter(Boolean);
  if (s.checked === 0) return "Nothing new to handle.";
  return `Checked ${s.checked} new message${s.checked === 1 ? "" : "s"}${parts.length ? `: ${parts.join(", ")}` : "; no rule applied"}.`;
}

function PlatformRules({
  item,
  maxCap,
  sendingEnabled,
  saving,
  error,
  onSave,
}: Readonly<{
  item: AutopilotPlatform;
  maxCap: number;
  sendingEnabled: boolean;
  saving: boolean;
  error: string;
  onSave: (changes: Partial<AutopilotRules>) => void;
}>) {
  const capId = React.useId();
  const wordsId = React.useId();
  const modeId = React.useId();
  const [cap, setCap] = React.useState(String(item.daily_cap));
  const [words, setWords] = React.useState(item.blocked_words.join(", "));

  React.useEffect(() => setCap(String(item.daily_cap)), [item.daily_cap]);
  React.useEffect(() => setWords(item.blocked_words.join(", ")), [item.blocked_words]);

  const readable = item.support.read === "yes";
  const off = !item.enabled;

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="font-semibold">{item.label}</p>
          <div className="flex items-center gap-2">
            {saving && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden />}
            <Badge variant={item.enabled ? "success" : "outline"}>{item.enabled ? "On" : "Off"}</Badge>
          </div>
        </div>

        {!readable ? (
          <p className="text-sm text-muted-foreground">
            {item.support.reply_note || "Menivor can't read comments here, so there is nothing to automate."}
          </p>
        ) : (
          <>
            <Toggle
              label="Autopilot on"
              hint="Applies these rules to new comments and messages about every 5 minutes."
              checked={item.enabled}
              disabled={saving}
              onChange={(v) => onSave({ enabled: v })}
            />
            <div className="space-y-3 border-l border-border pl-4">
              <Toggle
                label="Like positive comments"
                hint={item.support.like ? undefined : item.support.like_note}
                checked={item.auto_like && item.support.like}
                disabled={saving || off || !item.support.like}
                onChange={(v) => onSave({ auto_like: v })}
              />
              <div className="space-y-1">
                <label htmlFor={modeId} className="text-sm">
                  Replies to positive comments
                </label>
                <Select
                  id={modeId}
                  value={item.reply_mode}
                  disabled={saving || off}
                  onChange={(e) => onSave({ reply_mode: e.target.value as ReplyModeSetting })}
                >
                  <option value="approve">Draft a reply for me to approve</option>
                  <option value="auto">Send the reply automatically</option>
                  <option value="off">Don&apos;t reply</option>
                </Select>
                {item.reply_mode === "auto" && (item.support.reply !== "yes" || !sendingEnabled) && (
                  <p className="text-xs text-muted-foreground">
                    {item.support.reply !== "yes"
                      ? item.support.reply_note || "This platform does not allow replies from apps; replies stay drafts."
                      : "Sending from Menivor is not enabled for your account yet; replies stay drafts."}
                  </p>
                )}
              </div>
              <Toggle
                label="Also draft replies to questions"
                checked={item.reply_to_questions}
                disabled={saving || off || item.reply_mode === "off"}
                onChange={(v) => onSave({ reply_to_questions: v })}
              />
              <Toggle
                label="Hide spam"
                hint={item.support.hide ? undefined : item.support.hide_note || "Spam is flagged for you instead."}
                checked={item.hide_spam}
                disabled={saving || off}
                onChange={(v) => onSave({ hide_spam: v })}
              />
              <Toggle
                label="Hide abusive comments (they are always flagged)"
                hint={item.support.hide ? undefined : item.support.hide_note}
                checked={item.hide_abuse && item.support.hide}
                disabled={saving || off || !item.support.hide}
                onChange={(v) => onSave({ hide_abuse: v })}
              />
              <Toggle
                label="Send buying questions to Leads"
                checked={item.route_leads}
                disabled={saving || off}
                onChange={(v) => onSave({ route_leads: v })}
              />
              <div className="grid gap-3 sm:grid-cols-[8rem_1fr]">
                <div className="space-y-1">
                  <label htmlFor={capId} className="text-sm">
                    Daily limit
                  </label>
                  <Input
                    id={capId}
                    type="number"
                    min={0}
                    max={maxCap}
                    value={cap}
                    disabled={saving || off}
                    onChange={(e) => setCap(e.target.value)}
                    onBlur={() => {
                      const n = Math.max(0, Math.min(maxCap, Number.parseInt(cap, 10) || 0));
                      if (n !== item.daily_cap) onSave({ daily_cap: n });
                      else setCap(String(item.daily_cap));
                    }}
                  />
                </div>
                <div className="space-y-1">
                  <label htmlFor={wordsId} className="text-sm">
                    Always treat as spam
                  </label>
                  <Input
                    id={wordsId}
                    placeholder="words or phrases, comma separated"
                    value={words}
                    disabled={saving || off}
                    onChange={(e) => setWords(e.target.value)}
                    onBlur={() => {
                      const next = words.split(",").map((w) => w.trim().toLowerCase()).filter(Boolean);
                      if (next.join(",") !== item.blocked_words.join(",")) onSave({ blocked_words: next });
                    }}
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                {item.used_today} of {item.daily_cap} likes, hides and replies used today (UTC). Last run{" "}
                {relativeTime(item.last_run_at)}.
              </p>
            </div>
          </>
        )}
        {error && (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** Autopilot rules per connected platform, with an honest "what this platform allows" per rule. */
export function AutopilotSettings({ getOptions, onChanged }: Readonly<AutopilotSettingsProps>) {
  const [data, setData] = React.useState<AutopilotOverview | null>(null);
  const [loadError, setLoadError] = React.useState("");
  const [saving, setSaving] = React.useState<string | null>(null);
  const [errors, setErrors] = React.useState<Readonly<Record<string, string>>>({});
  const [running, setRunning] = React.useState(false);
  const [runMessage, setRunMessage] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      setData(await getAutopilot(await getOptions()));
      setLoadError("");
    } catch (err) {
      setLoadError(cleanError(err, "Couldn't load autopilot settings."));
    }
  }, [getOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const save = async (platform: string, changes: Partial<AutopilotRules>) => {
    setSaving(platform);
    setErrors((prev) => ({ ...prev, [platform]: "" }));
    try {
      const updated = await updateAutopilot(platform as AutopilotPlatform["platform"], changes, await getOptions());
      setData((prev) =>
        prev ? { ...prev, platforms: prev.platforms.map((p) => (p.platform === updated.platform ? updated : p)) } : prev,
      );
    } catch (err) {
      setErrors((prev) => ({ ...prev, [platform]: cleanError(err, "Couldn't save.") }));
    } finally {
      setSaving(null);
    }
  };

  const run = async () => {
    setRunning(true);
    setRunMessage("");
    try {
      setRunMessage(summaryText(await runAutopilot(await getOptions())));
      await load();
      onChanged();
    } catch (err) {
      setRunMessage(cleanError(err, "Couldn't run the autopilot right now."));
    } finally {
      setRunning(false);
    }
  };

  if (loadError) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {loadError}
      </p>
    );
  }
  if (!data) {
    return (
      <div className="grid gap-3 md:grid-cols-2">
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const connected = data.platforms.filter((p) => p.connected);
  const anyOn = connected.some((p) => p.enabled);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">
          The autopilot is off until you turn it on for a platform. Replies wait for your approval unless you
          choose to send them automatically. Every action is recorded under Activity.
        </p>
        <div className="flex flex-col items-end gap-1">
          <Button size="sm" variant="outline" disabled={running || !anyOn} onClick={() => void run()}>
            {running ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />}
            Run now
          </Button>
          {runMessage && <span className="text-xs text-muted-foreground">{runMessage}</span>}
        </div>
      </div>

      {connected.length === 0 ? (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 p-5 text-sm">
            <p className="text-muted-foreground">Connect a platform to set up the autopilot.</p>
            <Button asChild size="sm" variant="outline">
              <Link href="/connections">
                <Plug className="size-4" aria-hidden /> Connections
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {connected.map((item) => (
            <PlatformRules
              key={item.platform}
              item={item}
              maxCap={data.max_daily_cap}
              sendingEnabled={data.sending_enabled}
              saving={saving === item.platform}
              error={errors[item.platform] ?? ""}
              onSave={(changes) => void save(item.platform, changes)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
