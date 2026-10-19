"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Languages, Loader2, RefreshCw, X } from "lucide-react";
import { ApiError, dubJob } from "@/lib/api";
import type { DubLanguage } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDubLanguages } from "@/components/dub/use-dub-languages";
import { LanguageMultiSelect } from "@/components/dub/LanguageMultiSelect";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface DubDialogProps {
  jobId: string;
  /** Source reel language code; excluded from the target list. Optional. */
  sourceLanguage?: string;
  open: boolean;
  onClose: () => void;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/** Drop the source language from the offered targets (case-insensitive). */
function excludeSource(
  languages: readonly DubLanguage[],
  sourceLanguage: string | undefined,
): readonly DubLanguage[] {
  const source = sourceLanguage?.trim().toLowerCase();
  if (!source || source === "auto") return languages;
  return languages.filter((l) => l.code.toLowerCase() !== source);
}

/**
 * Modal for dubbing a finished reel into N target languages. Fetches the
 * supported languages, lets the creator multi-select targets (excluding the
 * source language), shows the credit cost (1 per language), and on submit calls
 * POST /jobs/{id}/dub then routes to the shared batch-review page.
 */
export function DubDialog({
  jobId,
  sourceLanguage,
  open,
  onClose,
}: Readonly<DubDialogProps>) {
  const router = useRouter();
  const getApiToken = useApiToken();
  const titleId = React.useId();

  const { languages, status, error, reload } = useDubLanguages(open);
  const [selected, setSelected] = React.useState<readonly string[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string>("");

  const targets = React.useMemo(
    () => excludeSource(languages, sourceLanguage),
    [languages, sourceLanguage],
  );

  // Reset transient selection/error whenever the dialog is (re)opened.
  React.useEffect(() => {
    if (open) {
      setSelected([]);
      setSubmitError("");
      setSubmitting(false);
    }
  }, [open]);

  const requestClose = React.useCallback(() => {
    if (submitting) return;
    onClose();
  }, [submitting, onClose]);

  // Close on Escape while the dialog is open.
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, requestClose]);

  const toggle = React.useCallback((code: string) => {
    setSelected((prev) =>
      prev.includes(code)
        ? prev.filter((c) => c !== code)
        : [...prev, code],
    );
  }, []);

  const cost = selected.length;

  const handleSubmit = React.useCallback(async () => {
    if (cost === 0) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const token = await getApiToken();
      const result = await dubJob(jobId, [...selected], { token });
      // Route to the shared batch-review page; the dialog unmounts on
      // navigation, so no local state reset is needed.
      router.push(`/batch/${encodeURIComponent(result.batch_id)}`);
    } catch (err) {
      setSubmitError(errorMessageOf(err, "Failed to start dubbing."));
      setSubmitting(false);
    }
  }, [cost, getApiToken, jobId, selected, router]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <button
        type="button"
        aria-label="Close dialog"
        className="absolute inset-0 bg-black/60"
        onClick={requestClose}
      />

      <div className="relative z-10 flex max-h-[90dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl border border-border bg-card shadow-lg sm:rounded-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div className="space-y-1">
            <h2
              id={titleId}
              className="flex items-center gap-2 text-lg font-semibold"
            >
              <Languages className="size-5 text-primary" aria-hidden />
              Dub / Translate
            </h2>
            <p className="text-sm text-muted-foreground">
              Recreate this reel in other languages. Each keeps the same
              recording, avatar, voice, layout, and caption style.
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Close"
            onClick={requestClose}
            disabled={submitting}
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {status === "loading" || status === "idle" ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full rounded-lg" />
              ))}
            </div>
          ) : status === "error" ? (
            <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
              <div className="flex items-start gap-2">
                <AlertTriangle
                  className="mt-0.5 size-5 shrink-0 text-destructive"
                  aria-hidden
                />
                <p className="text-sm text-muted-foreground">{error}</p>
              </div>
              <Button variant="outline" size="sm" onClick={reload}>
                <RefreshCw className="size-4" aria-hidden /> Try again
              </Button>
            </div>
          ) : targets.length === 0 ? (
            <p className="rounded-lg border border-border p-4 text-sm text-muted-foreground">
              No other languages are available to dub into right now.
            </p>
          ) : (
            <LanguageMultiSelect
              languages={targets}
              selected={selected}
              disabled={submitting}
              onToggle={toggle}
            />
          )}

          {submitError && (
            <p className="mt-4 text-sm text-destructive">{submitError}</p>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border p-5">
          <span className="text-sm text-muted-foreground">
            {cost === 0
              ? "Select at least one language"
              : `${cost} credit${cost === 1 ? "" : "s"} · ${cost} language${
                  cost === 1 ? "" : "s"
                }`}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={requestClose}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void handleSubmit()}
              disabled={submitting || cost === 0 || status !== "ready"}
            >
              {submitting ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Languages className="size-4" aria-hidden />
              )}
              {submitting ? "Starting…" : "Generate dubs"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
