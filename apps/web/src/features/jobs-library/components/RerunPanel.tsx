"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, Wand2 } from "lucide-react";
import { ApiError, rerunJob } from "@/lib/api";
import type { Job, RerunOverrides } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { AvatarPicker } from "@/components/wizard/AvatarPicker";
import { VoicePicker } from "@/components/wizard/VoicePicker";
import { MusicPicker } from "./MusicPicker";
import {
  CAPTION_STYLE_OPTIONS,
  LANGUAGE_OPTIONS,
  LAYOUT_OPTIONS,
} from "@/components/wizard/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/**
 * "Re-run with tweaks" — clones the source job's params, applies only the
 * fields the user changes (avatar / voice / layout / caption style / music /
 * language), calls `POST /jobs/{id}/rerun`, and routes to the freshly created
 * job. Overrides are held immutably; unset fields reuse the source job.
 */

export interface RerunPanelProps {
  job: Job;
}

interface SelectOption {
  value: string;
  label: string;
}

const LAYOUT_SELECT: readonly SelectOption[] = LAYOUT_OPTIONS.map((o) => ({
  value: o.value,
  label: o.title,
}));
const CAPTION_SELECT: readonly SelectOption[] = CAPTION_STYLE_OPTIONS.map(
  (o) => ({ value: o.value, label: o.title }),
);
const LANGUAGE_SELECT: readonly SelectOption[] = LANGUAGE_OPTIONS.map((o) => ({
  value: o.value,
  label: o.label,
}));

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

export function RerunPanel({ job }: Readonly<RerunPanelProps>) {
  const router = useRouter();
  const getApiToken = useApiToken();

  const [overrides, setOverrides] = React.useState<RerunOverrides>({});
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string>("");

  // Immutable single-field update: empty/undefined removes the override so the
  // source job's value is reused.
  const setField = React.useCallback(
    <K extends keyof RerunOverrides>(
      key: K,
      value: RerunOverrides[K] | undefined,
    ) => {
      setOverrides((prev) => {
        const next = { ...prev };
        if (value === undefined || value === "") delete next[key];
        else next[key] = value;
        return next;
      });
    },
    [],
  );

  const changeCount = Object.keys(overrides).length;

  const handleSubmit = React.useCallback(async () => {
    setSubmitting(true);
    setError("");
    try {
      const token = await getApiToken();
      const created = await rerunJob(job.job_id, overrides, { token });
      // Navigate to the new job; keep `submitting` true — this component
      // unmounts on route change, so no state reset is needed.
      router.push(`/reels/${encodeURIComponent(created.job_id)}`);
    } catch (err) {
      setError(errorMessageOf(err, "Failed to start the re-run."));
      setSubmitting(false);
    }
  }, [getApiToken, job.job_id, overrides, router]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Wand2 className="size-5 text-primary" aria-hidden />
          Re-run with tweaks
        </CardTitle>
        <CardDescription>
          Clone this reel&apos;s settings, adjust any option below, and render a
          fresh variant. Unchanged fields reuse the original. Costs 1 credit.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <LabeledSelect
            id="rerun-layout"
            label="Layout"
            value={(overrides.layout as string | undefined) ?? ""}
            options={LAYOUT_SELECT}
            disabled={submitting}
            onChange={(v) => setField("layout", v || undefined)}
          />
          <LabeledSelect
            id="rerun-caption"
            label="Caption style"
            value={overrides.caption_style ?? ""}
            options={CAPTION_SELECT}
            disabled={submitting}
            onChange={(v) => setField("caption_style", v || undefined)}
          />
          <LabeledSelect
            id="rerun-language"
            label="Language"
            value={(overrides.language as string | undefined) ?? ""}
            options={LANGUAGE_SELECT}
            disabled={submitting}
            onChange={(v) => setField("language", v || undefined)}
          />
          <div className="space-y-1.5">
            <Label htmlFor="rerun-music">Background music</Label>
            <MusicPicker
              id="rerun-music"
              value={overrides.music_id ?? null}
              disabled={submitting}
              onChange={(v) => setField("music_id", v ?? undefined)}
            />
          </div>
        </div>

        <TweakDisclosure
          label="Avatar"
          changed={Boolean(overrides.avatar_id)}
          onClear={() => setField("avatar_id", undefined)}
        >
          <AvatarPicker
            value={overrides.avatar_id ?? null}
            onSelect={(avatarId) => setField("avatar_id", avatarId)}
          />
        </TweakDisclosure>

        <TweakDisclosure
          label="Voice"
          changed={Boolean(overrides.voice_id)}
          onClear={() => setField("voice_id", undefined)}
        >
          <VoicePicker
            value={overrides.voice_id ?? null}
            onSelect={(voiceId) => setField("voice_id", voiceId)}
          />
        </TweakDisclosure>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void handleSubmit()} disabled={submitting}>
            {submitting ? (
              <RefreshCw className="size-4 animate-spin" aria-hidden />
            ) : (
              <Wand2 className="size-4" aria-hidden />
            )}
            {submitting ? "Starting re-run…" : "Re-run job"}
          </Button>
          <span className="text-xs text-muted-foreground">
            {changeCount > 0
              ? `${changeCount} tweak${changeCount === 1 ? "" : "s"} applied`
              : "No tweaks — re-renders as-is"}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

interface LabeledSelectProps {
  id: string;
  label: string;
  value: string;
  options: readonly SelectOption[];
  disabled?: boolean;
  onChange: (value: string) => void;
}

function LabeledSelect({
  id,
  label,
  value,
  options,
  disabled,
  onChange,
}: Readonly<LabeledSelectProps>) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Keep original</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </Select>
    </div>
  );
}

interface TweakDisclosureProps {
  label: string;
  changed: boolean;
  onClear: () => void;
  children: React.ReactNode;
}

function TweakDisclosure({
  label,
  changed,
  onClear,
  children,
}: Readonly<TweakDisclosureProps>) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="rounded-lg border border-border">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <span className="flex items-center gap-2 text-sm font-medium">
          {label}
          {changed ? (
            <Badge variant="default">Changed</Badge>
          ) : (
            <span className="text-xs font-normal text-muted-foreground">
              Original
            </span>
          )}
        </span>
        <span className="flex items-center gap-2">
          {changed && (
            <Button variant="ghost" size="sm" onClick={onClear}>
              Clear
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? "Done" : "Change"}
          </Button>
        </span>
      </div>
      {open && <div className="border-t border-border p-4">{children}</div>}
    </div>
  );
}
