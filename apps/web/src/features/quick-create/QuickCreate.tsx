"use client";

/**
 * Quick Create — the zero-key core loop, proven end-to-end against the live
 * API: type a title (+ optional script), upload your own narration, pick a
 * curated background, pick a caption style -> POST /jobs with the avatar-less
 * `captions_only` layout -> the job page polls progress and plays the
 * rendered preview. Needs no avatar/voice provider keys and no signup — the
 * browser's device session (3 free credits) authorizes everything.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Coins,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import type { BackgroundClip } from "@/lib/types";
import { ApiError, createJob, getMe } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useGenerationCapabilities } from "@/lib/use-generation-capabilities";
import { useCreateAccess } from "@/src/shared/access";
import { GenerationUnavailableCta } from "@/components/marketing/GenerationUnavailableCta";
import { CaptionStylePicker } from "@/src/features/reel-create/components/CaptionStylePicker";
import { LANGUAGE_OPTIONS, coerceLanguage } from "@/components/wizard/types";
import {
  VoiceoverDropzone,
  type UploadedVoiceover,
} from "./components/VoiceoverDropzone";
import { BackgroundPicker } from "./components/BackgroundPicker";
import { formatLockOf, formatLockedMessage } from "@/src/shared/launch";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Preferred default background when the library carries it. */
const DEFAULT_BACKGROUND = "voxel-parkour";

interface FormState {
  title: string;
  script: string;
  voiceover: UploadedVoiceover | null;
  backgroundId: string;
  captionStyle: string;
  language: string;
}

const INITIAL_FORM: FormState = {
  title: "",
  script: "",
  voiceover: null,
  backgroundId: DEFAULT_BACKGROUND,
  captionStyle: "karaoke_yellow",
  language: "auto",
};

function friendlyCreateError(err: unknown): string {
  const lock = formatLockOf(err);
  if (lock) return formatLockedMessage(lock);
  if (err instanceof ApiError) {
    if (err.status === 402) {
      return "You are out of credits — top up in the wallet to keep rendering.";
    }
    if (err.status === 0) {
      return "We could not reach the render service. Check your connection and try again.";
    }
    return friendlyErrorMessage(err);
  }
  return friendlyErrorMessage(err, "Could not start the render.");
}

/** Where sign-up / the unlock step return to. */
const CREATE_ACCESS_BACK = "/create/advanced";

export function QuickCreate() {
  const router = useRouter();
  const device = useCreateAccess(CREATE_ACCESS_BACK);
  const { capabilities, loading: capsLoading, error: capsError } =
    useGenerationCapabilities();

  const [form, setForm] = React.useState<FormState>(INITIAL_FORM);
  const [credits, setCredits] = React.useState<number | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState("");

  const patch = React.useCallback(
    (partial: Partial<FormState>) =>
      setForm((prev) => ({ ...prev, ...partial })),
    [],
  );

  // Live credit balance once the device session is ready.
  React.useEffect(() => {
    if (device.status !== "ready") return;
    let active = true;
    const controller = new AbortController();
    void getMe({ signal: controller.signal })
      .then((me) => {
        if (active) setCredits(me.credits);
      })
      .catch(() => {
        // Non-blocking: the create call itself reports credit problems.
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [device.status]);

  const handleBackgroundsLoaded = React.useCallback(
    (clips: readonly BackgroundClip[]) => {
      setForm((prev) => {
        const stillValid = clips.some(
          (c) => c.id === prev.backgroundId && c.available,
        );
        if (stillValid) return prev;
        const fallback =
          clips.find((c) => c.id === DEFAULT_BACKGROUND && c.available) ??
          clips.find((c) => c.available);
        return { ...prev, backgroundId: fallback?.id ?? "" };
      });
    },
    [],
  );

  const canSubmit =
    form.title.trim().length > 0 && !!form.voiceover && !submitting;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit || !form.voiceover) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const result = await createJob({
        params: {
          video_subject: form.title.trim(),
          video_script: form.script.trim(),
          layout: "captions_only",
          background_id: form.backgroundId,
          caption_style: form.captionStyle,
          language: coerceLanguage(form.language, "auto"),
          // Avatar-less path: no provider voice/avatar and no screen
          // recording — the uploaded narration + curated background carry
          // the reel. `target_duration_s` is a fallback only; the BYOV
          // narration's real duration sizes the render.
          voice_name: "",
          avatar_id: "",
          avatar_provider: "heygen",
          aspect: "9:16",
          target_duration_s: 30,
          platforms: [],
          screen_recording_key: "",
        },
        voiceover_key: form.voiceover.key,
      });
      router.push(`/jobs/${encodeURIComponent(result.job_id)}`);
    } catch (err) {
      setSubmitError(friendlyCreateError(err));
      setSubmitting(false);
    }
  };

  if (device.status === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex flex-col items-start gap-4 p-6">
          <p className="flex items-start gap-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {device.error}
          </p>
          <Button type="button" variant="outline" size="sm" onClick={device.retry}>
            <RefreshCw className="size-4" aria-hidden /> Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (capsLoading || device.status === "loading") {
    return (
      <div className="flex items-center gap-2 py-12 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        Preparing your studio…
      </div>
    );
  }

  if (capsError || !capabilities?.generation?.reels) {
    return <GenerationUnavailableCta />;
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">1. What is this reel about?</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">Title</span>
            <input
              type="text"
              value={form.title}
              onChange={(e) => patch({ title: e.target.value })}
              placeholder="e.g. 3 focus hacks nobody talks about"
              maxLength={200}
              required
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">
              Script <span className="font-normal text-muted-foreground">(optional)</span>
            </span>
            <textarea
              value={form.script}
              onChange={(e) => patch({ script: e.target.value })}
              placeholder="If your narration audio is hard to transcribe, paste the exact words here — they become the caption fallback."
              rows={3}
              maxLength={5000}
              className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">2. Upload your narration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <VoiceoverDropzone
            value={form.voiceover}
            onUploaded={(voiceover) => patch({ voiceover })}
            onClear={() => patch({ voiceover: null })}
          />
          <p className="text-xs text-muted-foreground">
            Your voice sets the reel&apos;s length; we transcribe it into
            word-timed karaoke captions.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">3. Pick the background footage</CardTitle>
        </CardHeader>
        <CardContent>
          <BackgroundPicker
            value={form.backgroundId}
            onSelect={(backgroundId) => patch({ backgroundId })}
            onLoaded={handleBackgroundsLoaded}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">4. Captions</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <CaptionStylePicker
            value={form.captionStyle}
            onSelect={(captionStyle) => patch({ captionStyle })}
          />
          <label className="block max-w-xs">
            <span className="mb-1.5 block text-sm font-medium">Caption language</span>
            <select
              value={form.language}
              onChange={(e) => patch({ language: e.target.value })}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </CardContent>
      </Card>

      {submitError && (
        <div className="flex items-start justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
          <p className="flex items-start gap-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {submitError}
          </p>
          {submitError.includes("credits") && (
            <Button asChild variant="outline" size="sm">
              <Link href="/wallet/plans">View plans</Link>
            </Button>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Coins className="size-4" aria-hidden />
          {credits === null
            ? "Costs 1 credit per render."
            : `${credits} credit${credits === 1 ? "" : "s"} left — this render uses 1.`}
        </p>
        <Button type="submit" disabled={!canSubmit} size="lg">
          {submitting ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <Sparkles className="size-4" aria-hidden />
          )}
          {submitting ? "Starting render…" : "Generate reel"}
        </Button>
      </div>
    </form>
  );
}
