"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Plus, Scissors, Trash2, Type } from "lucide-react";

import { ApiError, createTimelineExport } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { formatTimecode, mapJobToEditorSource } from "./model";
import { useEditorJob } from "./use-editor-job";
import {
  newOverlay,
  newSegment,
  timelineDuration,
  validateTimeline,
  type OverlayPosition,
  type TextOverlay,
  type TimelineSegment,
} from "./timeline-model";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface TimelineEditorProps {
  sourceJobId: string;
  sourceDuration: number;
  /** Optional seed range from the single-cut view. */
  initialIn?: number;
  initialOut?: number;
  onExported?: (jobId: string) => void;
}

interface PendingTimelineCommand {
  signature: string;
  idempotencyKey: string;
}

function idempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `timeline-${crypto.randomUUID()}`;
  }
  return `timeline-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * OpenCut-style non-destructive timeline: assemble source trims (each with a
 * speed + optional caption) plus time-anchored text overlays, then submit the
 * EDL. The server validates + renders — this component only builds the EDL.
 */
export function TimelineEditor({
  sourceJobId,
  sourceDuration,
  initialIn = 0,
  initialOut,
  onExported,
}: TimelineEditorProps) {
  const { getToken } = useAuth();
  const [segments, setSegments] = React.useState<TimelineSegment[]>(() => [
    newSegment(initialIn, initialOut ?? Math.min(sourceDuration, initialIn + 15)),
  ]);
  const [overlays, setOverlays] = React.useState<TextOverlay[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const [exportJobId, setExportJobId] = React.useState("");
  const pending = React.useRef<PendingTimelineCommand | null>(null);
  const inFlight = React.useRef(false);
  const previousSourceJobId = React.useRef(sourceJobId);
  const currentSourceJobId = React.useRef(sourceJobId);
  currentSourceJobId.current = sourceJobId;
  const exportJob = useEditorJob(exportJobId);
  const exportedSource = exportJob.job ? mapJobToEditorSource(exportJob.job) : null;

  React.useEffect(() => {
    if (previousSourceJobId.current === sourceJobId) return;
    previousSourceJobId.current = sourceJobId;
    setSegments([
      newSegment(initialIn, initialOut ?? Math.min(sourceDuration, initialIn + 15)),
    ]);
    setOverlays([]);
    setError("");
    setExportJobId("");
    setSubmitting(false);
    pending.current = null;
    inFlight.current = false;
  }, [initialIn, initialOut, sourceDuration, sourceJobId]);

  const outputDuration = timelineDuration(segments);
  const validation = validateTimeline(segments, overlays, sourceDuration);

  const patchSegment = (id: string, patch: Partial<TimelineSegment>) =>
    setSegments((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  const patchOverlay = (id: string, patch: Partial<TextOverlay>) =>
    setOverlays((prev) => prev.map((o) => (o.id === id ? { ...o, ...patch } : o)));

  const addSegment = () =>
    setSegments((prev) => [
      ...prev,
      newSegment(0, Math.min(sourceDuration, 15)),
    ]);

  const onExport = React.useCallback(async () => {
    if (validation || inFlight.current) return;
    const body = {
      segments: segments.map((s) => ({
        source_in: Number(s.sourceIn.toFixed(3)),
        source_out: Number(s.sourceOut.toFixed(3)),
        speed: Number(s.speed.toFixed(3)),
        caption: s.caption.trim() || null,
      })),
      overlays: overlays.map((o) => ({
        text: o.text.trim(),
        start_s: Number(o.startS.toFixed(3)),
        end_s: Number(o.endS.toFixed(3)),
        position: o.position,
      })),
    };
    const signature = JSON.stringify({ sourceJobId, body });
    if (!pending.current || pending.current.signature !== signature) {
      pending.current = { signature, idempotencyKey: idempotencyKey() };
    }
    const commandKey = pending.current.idempotencyKey;
    const submittedSourceJobId = sourceJobId;
    inFlight.current = true;
    setSubmitting(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const job = await createTimelineExport(
        sourceJobId,
        body,
        { token, idempotencyKey: commandKey },
      );
      if (currentSourceJobId.current !== submittedSourceJobId) return;
      setExportJobId(job.job_id);
      pending.current = null;
      onExported?.(job.job_id);
    } catch (err) {
      if (currentSourceJobId.current !== submittedSourceJobId) return;
      setError(
        friendlyErrorMessage(err, "The timeline could not be exported."),
      );
    } finally {
      if (currentSourceJobId.current === submittedSourceJobId) {
        inFlight.current = false;
        setSubmitting(false);
      }
    }
  }, [getToken, onExported, overlays, segments, sourceJobId, validation]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Scissors className="h-4 w-4 text-primary" aria-hidden /> Timeline
          <span className="font-normal text-muted-foreground">
            {segments.length} clip{segments.length === 1 ? "" : "s"} · {formatTimecode(outputDuration)}
          </span>
        </h3>
        <Button size="sm" variant="outline" onClick={addSegment}>
          <Plus className="mr-1 h-4 w-4" aria-hidden /> Clip
        </Button>
      </div>

      <div className="space-y-2">
        {segments.map((seg, i) => (
          <Card key={seg.id}>
            <CardContent className="grid gap-2 py-3 sm:grid-cols-[auto_1fr_1fr_1fr_auto] sm:items-end">
              <span className="text-xs font-medium text-muted-foreground">#{i + 1}</span>
              <NumField
                label="In (s)"
                value={seg.sourceIn}
                onChange={(v) => patchSegment(seg.id, { sourceIn: v })}
              />
              <NumField
                label="Out (s)"
                value={seg.sourceOut}
                onChange={(v) => patchSegment(seg.id, { sourceOut: v })}
              />
              <NumField
                label="Speed"
                step={0.25}
                value={seg.speed}
                onChange={(v) => patchSegment(seg.id, { speed: v })}
              />
              <Button
                size="icon"
                variant="ghost"
                aria-label="Remove clip"
                disabled={segments.length === 1}
                onClick={() => setSegments((p) => p.filter((s) => s.id !== seg.id))}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
              <Input
                className="sm:col-span-5"
                placeholder="Caption for this clip (optional)"
                value={seg.caption}
                maxLength={200}
                onChange={(e) => patchSegment(seg.id, { caption: e.target.value })}
              />
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex items-center justify-between">
        <h4 className="flex items-center gap-2 text-sm font-medium">
          <Type className="h-4 w-4 text-primary" aria-hidden /> Text overlays
        </h4>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setOverlays((p) => [...p, newOverlay(Math.min(3, outputDuration))])}
        >
          <Plus className="mr-1 h-4 w-4" aria-hidden /> Overlay
        </Button>
      </div>

      {overlays.map((ov, i) => (
        <Card key={ov.id}>
          <CardContent className="grid gap-2 py-3 sm:grid-cols-[1fr_auto_auto_auto_auto] sm:items-end">
            <Input
              placeholder={`Overlay ${i + 1} text`}
              value={ov.text}
              maxLength={200}
              onChange={(e) => patchOverlay(ov.id, { text: e.target.value })}
            />
            <NumField label="Start" value={ov.startS} onChange={(v) => patchOverlay(ov.id, { startS: v })} />
            <NumField label="End" value={ov.endS} onChange={(v) => patchOverlay(ov.id, { endS: v })} />
            <select
              aria-label="Overlay position"
              value={ov.position}
              onChange={(e) => patchOverlay(ov.id, { position: e.target.value as OverlayPosition })}
              className="rounded-md border border-input bg-background px-2 py-2 text-sm"
            >
              <option value="top">Top</option>
              <option value="center">Center</option>
              <option value="bottom">Bottom</option>
            </select>
            <Button
              size="icon"
              variant="ghost"
              aria-label="Remove overlay"
              onClick={() => setOverlays((p) => p.filter((o) => o.id !== ov.id))}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </Button>
          </CardContent>
        </Card>
      ))}

      {(validation || error) && (
        <p role="alert" className="text-sm text-destructive">{error || validation}</p>
      )}

      <Button onClick={() => void onExport()} disabled={submitting || Boolean(validation)}>
        {submitting ? "Exporting…" : `Export timeline (${formatTimecode(outputDuration)})`}
      </Button>

      {exportJobId && !exportedSource?.terminal && exportJob.status !== "error" && (
        <p role="status" className="text-sm text-muted-foreground">
          Timeline export {exportedSource?.progress ?? 0}% · {exportJobId.slice(0, 12)}
        </p>
      )}
      {exportJob.status === "error" && (
        <p role="alert" className="text-sm text-destructive">
          {exportJob.error}
        </p>
      )}
      {exportedSource?.failed && (
        <p role="alert" className="text-sm text-destructive">
          {exportedSource.error || "The timeline export failed in the render worker."}
        </p>
      )}
      {exportedSource?.terminal && !exportedSource.failed && exportedSource.resultUrl && (
        <a
          href={exportedSource.resultUrl}
          download
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex h-10 items-center border border-primary px-4 text-sm text-primary"
        >
          Download timeline export
        </a>
      )}
      {exportJobId && (
        <a href={`/jobs/${encodeURIComponent(exportJobId)}`} className="block text-sm underline">
          Open export job
        </a>
      )}
    </div>
  );
}

function NumField({
  label,
  value,
  onChange,
  step = 0.1,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
}) {
  return (
    <label className="grid gap-1 text-xs text-muted-foreground">
      {label}
      <Input
        type="number"
        step={step}
        min={0}
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-24"
      />
    </label>
  );
}
