"use client";

import * as React from "react";
import { AlertCircle, Check, Loader2, Send } from "lucide-react";
import {
  PERFORMANCE_COUNT_FIELDS,
  PUBLISH_PLATFORMS,
  RETENTION_PCT_MAX,
  RETENTION_PCT_MIN,
  type JobPerformance,
  type LogPerformanceRequest,
  type PerformanceCountField,
} from "@/lib/types";
import { ApiError, logJobPerformance } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Human-readable label for each self-reported count field. */
const COUNT_LABELS: Record<PerformanceCountField, string> = {
  views: "Views",
  likes: "Likes",
  comments: "Comments",
  shares: "Shares",
  saves: "Saves",
};

/** Display label for a known publish platform id. */
function platformLabel(id: string): string {
  switch (id) {
    case "tiktok":
      return "TikTok";
    case "instagram":
      return "Instagram";
    case "youtube_shorts":
      return "YouTube Shorts";
    default:
      return id;
  }
}

type Phase =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "error"; message: string }
  | { status: "saved" };

type CountState = Record<PerformanceCountField, string>;

const EMPTY_COUNTS: CountState = {
  views: "",
  likes: "",
  comments: "",
  shares: "",
  saves: "",
};

/** Parse a non-negative integer from a raw input. `""` is a valid (omitted) value. */
function parseCount(raw: string): { value?: number; error?: string } {
  const trimmed = raw.trim();
  if (trimmed === "") return {};
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0) {
    return { error: "Must be a non-negative number." };
  }
  return { value: Math.trunc(n) };
}

/** Parse a retention percentage in `[0, 100]`. `""` is a valid (omitted) value. */
function parseRetention(raw: string): { value?: number; error?: string } {
  const trimmed = raw.trim();
  if (trimmed === "") return {};
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < RETENTION_PCT_MIN || n > RETENTION_PCT_MAX) {
    return { error: `Must be between ${RETENTION_PCT_MIN} and ${RETENTION_PCT_MAX}.` };
  }
  return { value: n };
}

export interface LogMetricsFormProps {
  /** Optional job id to prefill (e.g. deep-linked from a reel). */
  initialJobId?: string;
  /** Called with the stored record after a successful log/update. */
  onLogged?: (performance: JobPerformance) => void;
}

/**
 * A form to LOG (or re-log) a reel's real-world performance metrics for a given
 * job id. Every numeric input is validated client-side (non-negative counts,
 * retention in `[0, 100]`) before the call, and the fetcher clamps again at the
 * API boundary. Ownership is enforced server-side — a foreign job is a 403, an
 * unknown one a 404, both surfaced inline. State is updated immutably.
 */
export function LogMetricsForm({
  initialJobId,
  onLogged,
}: Readonly<LogMetricsFormProps>) {
  const getApiToken = useApiToken();

  const [jobId, setJobId] = React.useState(initialJobId ?? "");
  const [platform, setPlatform] = React.useState("");
  const [counts, setCounts] = React.useState<CountState>(EMPTY_COUNTS);
  const [retention, setRetention] = React.useState("");
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });
  const [fieldErrors, setFieldErrors] = React.useState<
    Partial<Record<string, string>>
  >({});

  const submitting = phase.status === "submitting";

  const setCount = React.useCallback(
    (field: PerformanceCountField, value: string) => {
      setCounts((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (submitting) return;

      const errors: Record<string, string> = {};
      const trimmedJobId = jobId.trim();
      if (!trimmedJobId) errors.jobId = "A job id is required.";

      const body: LogPerformanceRequest = {};
      const trimmedPlatform = platform.trim();
      if (trimmedPlatform) body.platform = trimmedPlatform;

      for (const field of PERFORMANCE_COUNT_FIELDS) {
        const parsed = parseCount(counts[field]);
        if (parsed.error) errors[field] = parsed.error;
        else if (parsed.value !== undefined) body[field] = parsed.value;
      }

      const parsedRetention = parseRetention(retention);
      if (parsedRetention.error) errors.retention_pct = parsedRetention.error;
      else if (parsedRetention.value !== undefined) {
        body.retention_pct = parsedRetention.value;
      }

      setFieldErrors(errors);
      if (Object.keys(errors).length > 0) {
        setPhase({ status: "idle" });
        return;
      }

      setPhase({ status: "submitting" });
      try {
        const token = await getApiToken();
        const stored = await logJobPerformance(trimmedJobId, body, { token });
        setPhase({ status: "saved" });
        onLogged?.(stored);
      } catch (err) {
        const message =
          friendlyErrorMessage(err, "Could not log these metrics. Please try again.");
        setPhase({ status: "error", message });
      }
    },
    [counts, getApiToken, jobId, onLogged, platform, retention, submitting],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Log reel performance</CardTitle>
      </CardHeader>
      <CardContent>
        <form className="space-y-5" onSubmit={handleSubmit} noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="perf-job-id">Job id</Label>
              <Input
                id="perf-job-id"
                value={jobId}
                onChange={(e) => {
                  setJobId(e.target.value);
                  if (phase.status !== "idle") setPhase({ status: "idle" });
                }}
                placeholder="job_…"
                disabled={submitting}
                aria-invalid={Boolean(fieldErrors.jobId)}
                autoComplete="off"
              />
              {fieldErrors.jobId ? (
                <p className="text-xs text-destructive">{fieldErrors.jobId}</p>
              ) : null}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="perf-platform">Platform</Label>
              <Select
                id="perf-platform"
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                disabled={submitting}
              >
                <option value="">Not specified</option>
                {PUBLISH_PLATFORMS.map((p) => (
                  <option key={p} value={p}>
                    {platformLabel(p)}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            {PERFORMANCE_COUNT_FIELDS.map((field) => (
              <div key={field} className="space-y-1.5">
                <Label htmlFor={`perf-${field}`}>{COUNT_LABELS[field]}</Label>
                <Input
                  id={`perf-${field}`}
                  type="number"
                  inputMode="numeric"
                  min={0}
                  step={1}
                  value={counts[field]}
                  onChange={(e) => setCount(field, e.target.value)}
                  placeholder="0"
                  disabled={submitting}
                  aria-invalid={Boolean(fieldErrors[field])}
                />
                {fieldErrors[field] ? (
                  <p className="text-xs text-destructive">
                    {fieldErrors[field]}
                  </p>
                ) : null}
              </div>
            ))}

            <div className="space-y-1.5">
              <Label htmlFor="perf-retention">Retention %</Label>
              <Input
                id="perf-retention"
                type="number"
                inputMode="decimal"
                min={RETENTION_PCT_MIN}
                max={RETENTION_PCT_MAX}
                step="any"
                value={retention}
                onChange={(e) => setRetention(e.target.value)}
                placeholder="0–100"
                disabled={submitting}
                aria-invalid={Boolean(fieldErrors.retention_pct)}
              />
              {fieldErrors.retention_pct ? (
                <p className="text-xs text-destructive">
                  {fieldErrors.retention_pct}
                </p>
              ) : null}
            </div>
          </div>

          {phase.status === "error" ? (
            <p
              role="alert"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              {phase.message}
            </p>
          ) : null}

          {phase.status === "saved" ? (
            <p className="flex items-center gap-2 text-sm text-success">
              <Check className="size-4 shrink-0" aria-hidden />
              Metrics saved for this reel.
            </p>
          ) : null}

          <div className="flex items-center gap-3">
            <Button type="submit" disabled={submitting}>
              {submitting ? (
                <>
                  <Loader2 className="animate-spin" /> Saving…
                </>
              ) : (
                <>
                  <Send /> Log metrics
                </>
              )}
            </Button>
            <p className="text-xs text-muted-foreground">
              Re-logging the same reel updates its record.
            </p>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
