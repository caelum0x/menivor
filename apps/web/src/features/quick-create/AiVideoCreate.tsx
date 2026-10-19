"use client";

/**
 * AI video — the metered text/image → video tab of /create (Replicate-hosted
 * Wan 2.2). Submits `POST /generation/broll/generate` through the shared
 * device session and reuses the existing generation polling flow
 * (`useBrollStudio`) until the rendered clip's presigned preview/download URL
 * arrives. Honest about money: the 3-credit price is shown up front, and the
 * server-enforced daily caps (2/user, 20 global) surface as a clean
 * "at capacity today" state.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Clapperboard,
  Check,
  Clock,
  Coins,
  Download,
  Loader2,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import type { BrollGenMode, BrollGeneration } from "@/lib/types";
import { JobState, isFailedState, isTerminalState } from "@/lib/types";
import { ApiError, getMe, uploadAndRegisterImage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useCreateAccess } from "@/src/shared/access";
import { useGenerationCapabilities } from "@/lib/use-generation-capabilities";
import { GenerationUnavailableCta } from "@/components/marketing/GenerationUnavailableCta";
import { SelfieInput, type SelfiePhoto } from "@/components/avatars/SelfieInput";
import { useBrollStudio } from "@/src/features/broll-studio";
import { stashBrollAttachment } from "@/src/shared/media";
import {
  formatLockOf,
  formatLockedMessage,
  lockFor,
  lockedOptionReason,
  useFormatAvailability,
} from "@/src/shared/launch";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

const PROMPT_MAX = 500;

/** Matches the live backend's AI_VIDEO_CREDIT_COST (display only — the server debits). */
export const AI_VIDEO_CREDIT_COST = 3;
/** Matches AI_VIDEO_USER_DAILY_CAP on the live backend (display only). */
export const AI_VIDEO_USER_DAILY_CAP = 2;

type SubmitBlock =
  | { kind: "none" }
  | { kind: "credits"; message: string }
  | { kind: "capacity"; message: string }
  | { kind: "locked"; message: string }
  | { kind: "error"; message: string };

/** Where sign-up / the unlock step return to. */
const CREATE_ACCESS_BACK = "/create/advanced";

export function classifyError(err: unknown): SubmitBlock {
  const lock = formatLockOf(err);
  if (lock) return { kind: "locked", message: formatLockedMessage(lock) };
  if (err instanceof ApiError) {
    if (err.status === 402) {
      return {
        kind: "credits",
        message:
          "You are out of credits — each AI render uses 3. Top up to keep generating.",
      };
    }
    if (err.status === 429) {
      return {
        kind: "capacity",
        message:
          "AI video is at capacity today. Renders are capped to keep the beta free — try again tomorrow.",
      };
    }
    if (err.status === 503) {
      return {
        kind: "error",
        message:
          "AI video generation is temporarily unavailable. Please try again in a few minutes.",
      };
    }
    return { kind: "error", message: friendlyErrorMessage(err) };
  }
  return {
    kind: "error",
    message: friendlyErrorMessage(err, "Could not start the render."),
  };
}

export function AiVideoCreate() {
  const device = useCreateAccess(CREATE_ACCESS_BACK);
  const { capabilities, loading: capsLoading, error: capsError } =
    useGenerationCapabilities();
  const { generations, generate } = useBrollStudio();
  const { availability } = useFormatAvailability();
  const aiLock = lockFor(availability, "ai_broll");

  const [prompt, setPrompt] = React.useState("");
  const [mode, setMode] = React.useState<BrollGenMode>("t2v");
  const [image, setImage] = React.useState<SelfiePhoto | null>(null);
  const [credits, setCredits] = React.useState<number | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [block, setBlock] = React.useState<SubmitBlock>({ kind: "none" });
  // Only surface generations started from THIS form, newest first.
  const [sessionIds, setSessionIds] = React.useState<readonly string[]>([]);

  const refreshCredits = React.useCallback((signal?: AbortSignal) => {
    void getMe({ signal })
      .then((me) => setCredits(me.credits))
      .catch(() => {
        // Non-blocking: the create call itself reports credit problems.
      });
  }, []);

  React.useEffect(() => {
    if (device.status !== "ready") return;
    const controller = new AbortController();
    refreshCredits(controller.signal);
    return () => controller.abort();
  }, [device.status, refreshCredits]);

  const sessionGenerations = React.useMemo(
    () =>
      sessionIds
        .map((id) => generations.find((g) => g.generation_id === id))
        .filter((g): g is BrollGeneration => g !== undefined),
    [sessionIds, generations],
  );

  const canSubmit =
    !submitting &&
    aiLock === null &&
    prompt.trim().length > 0 &&
    (mode === "t2v" || image !== null) &&
    device.status === "ready";

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setBlock({ kind: "none" });
    try {
      let imageKey: string | undefined;
      if (mode === "i2v" && image) {
        // Existing presign flow: upload + register the owned reference image.
        imageKey = await uploadAndRegisterImage(image.file);
      }
      const snapshot = await generate({
        prompt: prompt.trim(),
        mode,
        ...(imageKey ? { image_key: imageKey } : {}),
      });
      setSessionIds((prev) => [snapshot.generation_id, ...prev]);
      setPrompt("");
      setImage(null);
      refreshCredits();
    } catch (err) {
      setBlock(classifyError(err));
    } finally {
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
        Preparing the AI studio…
      </div>
    );
  }

  if (capsError || !capabilities?.generation?.broll) {
    return <GenerationUnavailableCta />;
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Generation mode">
              <ModeChip
                active={mode === "t2v"}
                onClick={() => setMode("t2v")}
                disabled={submitting}
                label="Text to video"
              />
              <ModeChip
                active={mode === "i2v"}
                onClick={() => setMode("i2v")}
                disabled={submitting}
                label="Animate an image"
              />
            </div>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium">
                Describe your video
              </span>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value.slice(0, PROMPT_MAX))}
                placeholder="A tiny origami boat sailing across a rain puddle at dusk, cinematic close-up, soft reflections"
                rows={4}
                required
                className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <span className="mt-1 flex items-center justify-between text-xs text-muted-foreground">
                <span>Renders a ~5s 9:16 clip with the Wan 2.2 video model.</span>
                <span>
                  {prompt.length}/{PROMPT_MAX}
                </span>
              </span>
            </label>

            {mode === "i2v" && (
              <div className="space-y-2">
                <span className="block text-sm font-medium">Reference image</span>
                <SelfieInput value={image} onChange={setImage} disabled={submitting} />
                <p className="text-xs text-muted-foreground">
                  Your image becomes the first frame and animates from there.
                  Only upload an image you own or are authorized to use.
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {aiLock && (
          <p
            role="status"
            className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 p-4 text-sm text-muted-foreground"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {`${aiLock.label}. ${lockedOptionReason(aiLock)}`}
          </p>
        )}

        {block.kind !== "none" && (
          <div className="flex items-start justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
            <p className="flex items-start gap-2 text-sm text-destructive">
              {block.kind === "capacity" ? (
                <Clock className="mt-0.5 size-4 shrink-0" aria-hidden />
              ) : (
                <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
              )}
              {block.message}
            </p>
            {block.kind === "credits" && (
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
              ? `Costs ${AI_VIDEO_CREDIT_COST} credits per AI render (max ${AI_VIDEO_USER_DAILY_CAP}/day).`
              : `${credits} credit${credits === 1 ? "" : "s"} left — this render uses ${AI_VIDEO_CREDIT_COST}. Max ${AI_VIDEO_USER_DAILY_CAP} AI renders/day.`}
          </p>
          <Button type="submit" disabled={!canSubmit} size="lg">
            {submitting ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Sparkles className="size-4" aria-hidden />
            )}
            {submitting ? "Starting render…" : "Generate AI video"}
          </Button>
        </div>
      </form>

      {sessionGenerations.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold tracking-tight">Your AI renders</h2>
          <ul className="space-y-3">
            {sessionGenerations.map((gen) => (
              <li key={gen.generation_id}>
                <AiGenerationRow gen={gen} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ModeChip({
  active,
  onClick,
  disabled,
  label,
}: Readonly<{
  active: boolean;
  onClick: () => void;
  disabled: boolean;
  label: string;
}>) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      disabled={disabled}
      className={
        active
          ? "rounded-full border border-primary bg-primary/10 px-4 py-1.5 text-sm font-medium text-primary"
          : "rounded-full border border-border px-4 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted"
      }
    >
      {label}
    </button>
  );
}

/** One in-flight/finished AI render: live progress, then preview + download. */
function AiGenerationRow({ gen }: Readonly<{ gen: BrollGeneration }>) {
  const router = useRouter();
  const terminal = isTerminalState(gen.state);
  const failed = isFailedState(gen.state);
  const complete = gen.state === JobState.Complete;

  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-center gap-2">
          {complete ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-600">
              <Check className="size-3" aria-hidden /> Ready
            </span>
          ) : failed ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
              <X className="size-3" aria-hidden /> Failed — credits refunded
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              <Loader2 className="size-3 animate-spin" aria-hidden /> Generating
              (~1–2 min)
            </span>
          )}
          <span className="truncate font-mono text-xs text-muted-foreground">
            {gen.generation_id.slice(0, 12)}
          </span>
        </div>

        {!terminal && (
          <Progress
            value={gen.progress}
            className="h-1.5"
            aria-label="Render progress"
          />
        )}

        {failed && gen.error && (
          <p className="text-xs text-destructive">{gen.error}</p>
        )}

        {complete && gen.result_url && (
          <div className="space-y-3">
            <div className="w-full max-w-[280px] overflow-hidden rounded-lg border border-border bg-black">
              <video
                src={gen.result_url}
                controls
                playsInline
                preload="metadata"
                className="aspect-[9/16] h-auto w-full"
                aria-label="Generated AI video preview"
              >
                Your browser does not support the video tag.{" "}
                <a href={gen.result_url}>Download the video</a> instead.
              </video>
            </div>
            <div className="flex flex-wrap gap-2">
              {gen.broll_key && (
                <Button
                  type="button"
                  size="sm"
                  onClick={() => {
                    stashBrollAttachment({
                      key: gen.broll_key ?? "",
                      resultUrl: gen.result_url ?? "",
                    });
                    router.push("/new");
                  }}
                >
                  <Clapperboard className="size-4" aria-hidden /> Make a reel
                  with this
                </Button>
              )}
              <Button asChild variant="outline" size="sm">
                <a
                  href={gen.result_url}
                  download
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Download className="size-4" aria-hidden /> Download
                </a>
              </Button>
              <Button asChild variant="ghost" size="sm">
                <Link href="/broll-library">All my AI clips</Link>
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
