"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertCircle,
  Download,
  ExternalLink,
  Loader2,
  Scissors,
  Send,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { TemplateDetail, TemplateInput } from "@/src/features/templates/api";
import { jobAssetUrl } from "./api";
import { useCompile } from "./useCompile";
import { ShareActions } from "@/src/features/share-actions/ShareActions";

interface TemplateComposeFormProps {
  template: TemplateDetail;
}

/** Seed input state from each field's declared default. */
function initialInputs(inputs: readonly TemplateInput[]): Record<string, string> {
  return inputs.reduce<Record<string, string>>((acc, field) => {
    acc[field.key] = field.default ?? "";
    return acc;
  }, {});
}

/** Every required field must be non-empty before compile is allowed. */
function missingRequired(
  inputs: readonly TemplateInput[],
  values: Record<string, string>,
): boolean {
  return inputs.some((f) => f.required && !values[f.key]?.trim());
}

/** Links from a compiled job into the rest of the reel toolset. */
function JobHandoffLinks({ jobId, ready }: { jobId: string; ready: boolean }) {
  const id = encodeURIComponent(jobId);
  return (
    <div className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm">
        <Link href={`/jobs/${id}`}>
          <ExternalLink className="mr-1 h-4 w-4" aria-hidden /> Open reel page
        </Link>
      </Button>
      {ready && (
        <>
          <Button asChild variant="outline" size="sm">
            <Link href={`/editor?job=${id}`}>
              <Scissors className="mr-1 h-4 w-4" aria-hidden /> Edit
            </Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link href={`/publish?job=${id}`}>
              <Send className="mr-1 h-4 w-4" aria-hidden /> Publish
            </Link>
          </Button>
        </>
      )}
    </div>
  );
}

/**
 * Collects a template's declared inputs, instantiates + compiles the reel, and
 * renders the live render-job progress and final asset. This is the real create
 * path — every submit POSTs the reel draft to `/jobs` and polls `/jobs/{id}`.
 */
export function TemplateComposeForm({ template }: TemplateComposeFormProps) {
  const { state, run, reset } = useCompile();
  const [values, setValues] = React.useState<Record<string, string>>(() =>
    initialInputs(template.inputs),
  );
  const [durationS, setDurationS] = React.useState<number>(
    template.default_duration_s,
  );

  const busy = state.phase === "compiling" || state.phase === "polling";
  const blocked = missingRequired(template.inputs, values);

  const handleSubmit = React.useCallback(
    (event: React.FormEvent) => {
      event.preventDefault();
      if (busy || blocked) return;
      run({ slug: template.slug, inputs: values, durationS });
    },
    [busy, blocked, run, template.slug, values, durationS],
  );

  const assetUrl = state.job ? jobAssetUrl(state.job) : undefined;

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <Card>
        <CardContent className="space-y-5 py-6">
          {template.inputs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              This template needs no extra inputs — just set a duration and
              compile.
            </p>
          ) : (
            template.inputs.map((field) => (
              <div key={field.key} className="space-y-1.5">
                <Label htmlFor={`field-${field.key}`}>
                  {field.label}
                  {field.required && (
                    <span className="ml-1 text-destructive" aria-hidden>
                      *
                    </span>
                  )}
                </Label>
                {field.choices.length > 0 ? (
                  <Select
                    id={`field-${field.key}`}
                    value={values[field.key] ?? ""}
                    disabled={busy}
                    onChange={(e) =>
                      setValues((prev) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                  >
                    <option value="">Select…</option>
                    {field.choices.map((choice) => (
                      <option key={choice} value={choice}>
                        {choice}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Input
                    id={`field-${field.key}`}
                    value={values[field.key] ?? ""}
                    disabled={busy}
                    placeholder={field.help || undefined}
                    onChange={(e) =>
                      setValues((prev) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                  />
                )}
                {field.help && (
                  <p className="text-xs text-muted-foreground">{field.help}</p>
                )}
              </div>
            ))
          )}

          <div className="space-y-1.5">
            <Label htmlFor="field-duration">Duration (seconds)</Label>
            <Input
              id="field-duration"
              type="number"
              min={template.min_duration_s}
              max={template.max_duration_s}
              value={durationS}
              disabled={busy}
              onChange={(e) => setDurationS(Number(e.target.value))}
            />
            <p className="text-xs text-muted-foreground">
              {template.min_duration_s}–{template.max_duration_s}s supported.
            </p>
          </div>
        </CardContent>
      </Card>

      {state.phase === "error" && (
        <p
          role="alert"
          className="flex items-center gap-2 text-sm text-destructive"
        >
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden />
          {state.error}
        </p>
      )}

      {state.phase === "polling" && state.job?.job_id && (
        <div role="status" className="space-y-2 text-sm text-muted-foreground">
          <p>
            Rendering in the background. You can leave this page — the reel keeps
            rendering and appears in your library.
          </p>
          <JobHandoffLinks jobId={state.job.job_id} ready={false} />
        </div>
      )}

      {state.phase === "error" && state.job?.job_id && (
        <JobHandoffLinks jobId={state.job.job_id} ready={false} />
      )}

      {state.phase === "timeout" && (
        <div role="status" className="space-y-2 text-sm text-muted-foreground">
          <p>
            Still rendering — this reel is taking longer than expected. It keeps
            rendering on our side; follow it on its reel page.
          </p>
          {state.job?.job_id && (
            <JobHandoffLinks jobId={state.job.job_id} ready={false} />
          )}
        </div>
      )}

      {state.phase === "done" && (
        <Card>
          <CardContent className="space-y-4 py-6">
            <div className="flex items-center gap-2">
              <Badge variant="secondary">Ready</Badge>
              <span className="text-sm font-medium">Your reel is rendered.</span>
            </div>
            {assetUrl ? (
              <>
                <video
                  data-testid="compose-result-video"
                  className="mx-auto aspect-[9/16] w-full max-w-xs rounded-lg bg-black"
                  src={assetUrl}
                  controls
                  playsInline
                />
                <Button asChild variant="outline" size="sm">
                  <a href={assetUrl} download>
                    <Download className="mr-1 h-4 w-4" aria-hidden /> Download
                  </a>
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Rendered, but no downloadable asset was returned yet.
              </p>
            )}
            {state.job?.job_id && assetUrl ? (
              <ShareActions source="reel" sourceId={state.job.job_id} kind="video" />
            ) : null}
            {state.job?.job_id && (
              <JobHandoffLinks jobId={state.job.job_id} ready />
            )}
            <Button type="button" variant="ghost" size="sm" onClick={reset}>
              Compose another
            </Button>
          </CardContent>
        </Card>
      )}

      {state.phase !== "done" && (
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={busy || blocked}>
            {busy ? (
              <>
                <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
                {state.phase === "compiling" ? "Compiling…" : "Rendering…"}
              </>
            ) : (
              <>
                <Sparkles className="mr-1 h-4 w-4" aria-hidden /> Compile reel
              </>
            )}
          </Button>
          {blocked && !busy && (
            <span className="text-xs text-muted-foreground">
              Fill in the required fields to continue.
            </span>
          )}
        </div>
      )}
    </form>
  );
}
