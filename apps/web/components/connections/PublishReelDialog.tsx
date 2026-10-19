"use client";

import * as React from "react";
import { CheckCircle2, ExternalLink, Loader2, Send, X } from "lucide-react";
import { ApiError } from "@/lib/api";
import type { Job, PublishResult, SocialProvider } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { providerLabel } from "@/components/connections/providers";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Backend caption cap for a direct publish (see publishJobTo). */
const CAPTION_MAX = 2200;

export interface PublishReelDialogProps {
  open: boolean;
  onClose: () => void;
  /** Providers the caller has connected (publish targets). */
  connectedProviders: readonly SocialProvider[];
  /** The caller's completed reels, newest first (publish sources). */
  jobs: readonly Job[];
  onPublish: (
    jobId: string,
    provider: SocialProvider,
    caption?: string,
  ) => Promise<PublishResult>;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/** A short, human label for a reel in the picker (hook line or id prefix). */
function jobLabel(job: Job): string {
  const hook = job.hook?.trim();
  if (hook) return hook.length > 60 ? `${hook.slice(0, 57)}…` : hook;
  return `Reel ${job.job_id.slice(0, 8)}`;
}

/**
 * Modal to publish one of the caller's OWN finished reels straight to a connected
 * provider. The creator picks a reel + a connected provider and an optional
 * caption, then submits POST /jobs/{id}/publish/{provider}. Ownership + readiness
 * are enforced server-side. SECURITY: no token is ever shown — the result is the
 * token-free {@link PublishResult} (external post id + public URL).
 */
export function PublishReelDialog({
  open,
  onClose,
  connectedProviders,
  jobs,
  onPublish,
}: Readonly<PublishReelDialogProps>) {
  const titleId = React.useId();
  const jobId = React.useId();
  const providerId = React.useId();
  const captionId = React.useId();

  const [selectedJob, setSelectedJob] = React.useState("");
  const [selectedProvider, setSelectedProvider] = React.useState("");
  const [caption, setCaption] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState("");
  const [result, setResult] = React.useState<PublishResult | null>(null);

  // Reset transient state whenever the dialog is (re)opened, seeding the first
  // available reel + provider so the common case needs no manual selection.
  React.useEffect(() => {
    if (!open) return;
    setSelectedJob(jobs[0]?.job_id ?? "");
    setSelectedProvider(String(connectedProviders[0] ?? ""));
    setCaption("");
    setSubmitError("");
    setSubmitting(false);
    setResult(null);
  }, [open, jobs, connectedProviders]);

  const requestClose = React.useCallback(() => {
    if (submitting) return;
    onClose();
  }, [submitting, onClose]);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, requestClose]);

  const canSubmit =
    selectedJob !== "" &&
    selectedProvider !== "" &&
    !submitting &&
    jobs.length > 0 &&
    connectedProviders.length > 0;

  const handleSubmit = React.useCallback(async () => {
    setSubmitError("");
    if (!selectedJob || !selectedProvider) {
      setSubmitError("Pick a reel and a connected provider.");
      return;
    }
    setSubmitting(true);
    try {
      const published = await onPublish(
        selectedJob,
        selectedProvider,
        caption,
      );
      setResult(published);
    } catch (err) {
      setSubmitError(errorMessageOf(err, "Failed to publish this reel."));
    } finally {
      setSubmitting(false);
    }
  }, [selectedJob, selectedProvider, caption, onPublish]);

  if (!open) return null;

  const noReels = jobs.length === 0;
  const noProviders = connectedProviders.length === 0;

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
              <Send className="size-5 text-primary" aria-hidden />
              Publish a reel
            </h2>
            <p className="text-sm text-muted-foreground">
              Send one of your finished reels straight to a connected account.
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

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          {result ? (
            <div className="space-y-4">
              <div className="flex items-start gap-3 rounded-lg border border-success/40 bg-success/5 p-4">
                <CheckCircle2
                  className="mt-0.5 size-5 shrink-0 text-success"
                  aria-hidden
                />
                <div className="min-w-0 space-y-1">
                  <p className="font-medium">
                    Published to {providerLabel(result.provider)}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Status: {result.status || "published"}
                  </p>
                  {result.url && (
                    <a
                      href={result.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 text-sm text-primary underline-offset-4 hover:underline"
                    >
                      <ExternalLink className="size-3.5" aria-hidden />
                      View post
                    </a>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <>
              {(noReels || noProviders) && (
                <p className="rounded-lg border border-border bg-secondary/40 p-3 text-sm text-muted-foreground">
                  {noProviders
                    ? "Connect a social account above before publishing."
                    : "Finish rendering a reel before publishing it."}
                </p>
              )}

              <div className="space-y-2">
                <Label htmlFor={jobId}>Reel</Label>
                <Select
                  id={jobId}
                  value={selectedJob}
                  disabled={submitting || noReels}
                  onChange={(e) => setSelectedJob(e.target.value)}
                >
                  {noReels && <option value="">No finished reels</option>}
                  {jobs.map((job) => (
                    <option key={job.job_id} value={job.job_id}>
                      {jobLabel(job)}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor={providerId}>Publish to</Label>
                <Select
                  id={providerId}
                  value={selectedProvider}
                  disabled={submitting || noProviders}
                  onChange={(e) => setSelectedProvider(e.target.value)}
                >
                  {noProviders && (
                    <option value="">No connected accounts</option>
                  )}
                  {connectedProviders.map((provider) => (
                    <option key={String(provider)} value={String(provider)}>
                      {providerLabel(provider)}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor={captionId}>Caption (optional)</Label>
                <Textarea
                  id={captionId}
                  rows={3}
                  maxLength={CAPTION_MAX}
                  value={caption}
                  disabled={submitting}
                  placeholder="Write a caption for the post…"
                  onChange={(e) => setCaption(e.target.value)}
                />
                <p className="text-right text-xs text-muted-foreground">
                  {caption.length}/{CAPTION_MAX}
                </p>
              </div>

              {submitError && (
                <p className="text-sm text-destructive">{submitError}</p>
              )}
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border p-5">
          {result ? (
            <Button onClick={onClose}>Done</Button>
          ) : (
            <>
              <Button
                variant="outline"
                onClick={requestClose}
                disabled={submitting}
              >
                Cancel
              </Button>
              <Button onClick={() => void handleSubmit()} disabled={!canSubmit}>
                {submitting ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Send className="size-4" aria-hidden />
                )}
                {submitting ? "Publishing…" : "Publish"}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
