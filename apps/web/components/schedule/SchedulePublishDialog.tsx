"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { CalendarClock, Loader2, X } from "lucide-react";
import { ApiError, schedulePublish } from "@/lib/api";
import type {
  PublishPlatform,
  SchedulePublishRequest,
  YouTubePrivacyStatus,
} from "@/lib/types";
import { YOUTUBE_PRIVACY_STATUSES } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { PlatformMultiSelect } from "@/components/schedule/PlatformMultiSelect";
import {
  includesYouTube,
  isFutureDatetime,
  localDatetimeToUtcISO,
  minScheduleValue,
} from "@/components/schedule/platforms";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface SchedulePublishDialogProps {
  jobId: string;
  open: boolean;
  onClose: () => void;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

const PRIVACY_LABELS: Record<YouTubePrivacyStatus, string> = {
  public: "Public",
  unlisted: "Unlisted",
  private: "Private",
};

/**
 * Modal for scheduling a finished reel to auto-publish. The creator multi-selects
 * platforms, picks a future date/time (interpreted in their local timezone and
 * sent to the backend as a UTC instant), and — when YouTube Shorts is a target —
 * chooses a visibility. On submit it calls POST /jobs/{id}/schedule then routes
 * to the scheduled-publishes list.
 */
export function SchedulePublishDialog({
  jobId,
  open,
  onClose,
}: Readonly<SchedulePublishDialogProps>) {
  const router = useRouter();
  const getApiToken = useApiToken();
  const titleId = React.useId();
  const whenId = React.useId();
  const privacyId = React.useId();

  const [platforms, setPlatforms] = React.useState<readonly PublishPlatform[]>(
    [],
  );
  const [when, setWhen] = React.useState<string>("");
  const [privacy, setPrivacy] = React.useState<YouTubePrivacyStatus>("public");
  const [submitting, setSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string>("");
  // `min` is captured on open so it stays stable while the dialog is mounted.
  const [minWhen, setMinWhen] = React.useState<string>("");

  // Reset transient state whenever the dialog is (re)opened.
  React.useEffect(() => {
    if (open) {
      setPlatforms([]);
      setWhen("");
      setPrivacy("public");
      setSubmitError("");
      setSubmitting(false);
      setMinWhen(minScheduleValue());
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

  const togglePlatform = React.useCallback((platform: PublishPlatform) => {
    setPlatforms((prev) =>
      prev.includes(platform)
        ? prev.filter((p) => p !== platform)
        : [...prev, platform],
    );
  }, []);

  const showPrivacy = includesYouTube(platforms);
  const futureOk = when !== "" && isFutureDatetime(when);
  const canSubmit = platforms.length > 0 && futureOk && !submitting;

  const handleSubmit = React.useCallback(async () => {
    setSubmitError("");
    if (platforms.length === 0) {
      setSubmitError("Select at least one platform.");
      return;
    }
    const scheduledAt = localDatetimeToUtcISO(when);
    if (!scheduledAt || !isFutureDatetime(when)) {
      setSubmitError("Pick a date and time in the future.");
      return;
    }

    const body: SchedulePublishRequest = {
      platforms: [...platforms],
      scheduled_at: scheduledAt,
    };
    if (includesYouTube(platforms)) {
      body.youtube_privacy_status = privacy;
    }

    setSubmitting(true);
    try {
      const token = await getApiToken();
      await schedulePublish(jobId, body, { token });
      // The dialog unmounts on navigation, so no local state reset is needed.
      router.push("/scheduled");
    } catch (err) {
      setSubmitError(errorMessageOf(err, "Failed to schedule publishing."));
      setSubmitting(false);
    }
  }, [platforms, when, privacy, getApiToken, jobId, router]);

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
              <CalendarClock className="size-5 text-primary" aria-hidden />
              Schedule publish
            </h2>
            <p className="text-sm text-muted-foreground">
              Auto-publish this reel to your platforms at a future time. You can
              cancel it any time before it runs.
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
          <div className="space-y-2">
            <Label>Platforms</Label>
            <PlatformMultiSelect
              selected={platforms}
              disabled={submitting}
              onToggle={togglePlatform}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor={whenId}>Publish at</Label>
            <Input
              id={whenId}
              type="datetime-local"
              value={when}
              min={minWhen}
              disabled={submitting}
              onChange={(e) => setWhen(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Uses your device timezone. Must be in the future.
            </p>
            {when !== "" && !futureOk && (
              <p className="text-xs text-destructive">
                Choose a time later than now.
              </p>
            )}
          </div>

          {showPrivacy && (
            <div className="space-y-2">
              <Label htmlFor={privacyId}>YouTube visibility</Label>
              <Select
                id={privacyId}
                value={privacy}
                disabled={submitting}
                onChange={(e) =>
                  setPrivacy(e.target.value as YouTubePrivacyStatus)
                }
              >
                {YOUTUBE_PRIVACY_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {PRIVACY_LABELS[status]}
                  </option>
                ))}
              </Select>
            </div>
          )}

          {submitError && (
            <p className="text-sm text-destructive">{submitError}</p>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border p-5">
          <span className="text-sm text-muted-foreground">
            {platforms.length === 0
              ? "Select at least one platform"
              : `${platforms.length} platform${
                  platforms.length === 1 ? "" : "s"
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
              disabled={!canSubmit}
            >
              {submitting ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <CalendarClock className="size-4" aria-hidden />
              )}
              {submitting ? "Scheduling…" : "Schedule"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
