"use client";

// Feature controller for the canonical reel create workflow.

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  Loader2,
  Sparkles,
} from "lucide-react";
import type {
  JobCreateRequest,
  JobCreateResult,
  ReelForgeParams,
  Template,
} from "@/lib/types";
import { ApiError, createJob, listTemplates } from "@/lib/api";
import { takeSparkPrefill } from "@/lib/spark-prefill";
import {
  clearBrollAttachment,
  loadBrollAttachment,
} from "@/src/shared/media";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import { useGenerationCapabilities } from "@/lib/use-generation-capabilities";
import {
  CAMERA_MOTION_OPTIONS,
  CAPTION_STYLE_OPTIONS,
  DEFAULT_WIZARD_STATE,
  LANGUAGE_OPTIONS,
  LAYOUT_OPTIONS,
  coerceLanguage,
  coerceLayout,
  type WizardState,
} from "@/components/wizard/types";
import { UploadDropzone } from "./components/UploadDropzone";
import { ScriptPromptField } from "./components/ScriptPromptField";
import { AvatarPicker } from "@/components/wizard/AvatarPicker";
import { VoiceStep } from "@/components/voiceover/VoiceStep";
import { LayoutPicker } from "./components/LayoutPicker";
import { CaptionStylePicker } from "./components/CaptionStylePicker";
import { MusicPicker } from "./components/MusicPicker";
import { TemplateGallery } from "./components/TemplateGallery";
import { VariantsSelector } from "./components/VariantsSelector";
import { AutoTightenToggle } from "./components/AutoTightenToggle";
import { EditingPolishSection } from "./components/EditingPolishSection";
import { ChargeToSelector } from "./components/ChargeToSelector";
import { ProfilePicker } from "./components/ProfilePicker";
import { EffectsPicker } from "./components/EffectsPicker";
import { SavePresetButton } from "@/components/presets/SavePresetButton";
import { GenerationUnavailableCta } from "@/components/marketing/GenerationUnavailableCta";
import type { PresetConfig } from "@/components/presets/preset-config";
import {
  firstLock,
  formatLockOf,
  formatLockedMessage,
  isCreditShortfall,
  lockFor,
  lockedOptionReason,
  requiredReelFormats,
  useFormatAvailability,
  type FormatAvailability,
  type LockedFormat,
} from "@/src/shared/launch";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface StepDef {
  id: string;
  title: string;
  subtitle: string;
  /** Whether the wizard may advance past this step. */
  isComplete: (state: WizardState) => boolean;
}

const STEPS: readonly StepDef[] = [
  {
    id: "template",
    title: "Template",
    subtitle: "Start from a curated template, or build from scratch.",
    isComplete: () => true,
  },
  {
    id: "upload",
    title: "Upload recording",
    subtitle: "Drop in the screen recording your reel is built around.",
    isComplete: (s) => Boolean(s.screenRecordingKey),
  },
  {
    id: "script",
    title: "Script & brief",
    subtitle: "Tell us the subject; add a custom script only if you want one.",
    isComplete: (s) => s.videoSubject.trim().length > 0,
  },
  {
    id: "avatar",
    title: "Avatar",
    subtitle: "Pick the talking-head presenter for your reel.",
    isComplete: (s) => Boolean(s.avatarId),
  },
  {
    id: "voice",
    title: "Voice",
    subtitle: "Choose a narration voice, or bring your own voiceover.",
    isComplete: (s) =>
      s.useOwnVoiceover ? Boolean(s.voiceoverKey) : Boolean(s.voiceId),
  },
  {
    id: "layout",
    title: "Layout",
    subtitle: "Decide how the presenter sits over your recording.",
    isComplete: () => true,
  },
  {
    id: "captions",
    title: "Captions",
    subtitle: "Pick the burned-in karaoke caption style.",
    isComplete: () => true,
  },
  {
    id: "music",
    title: "Music",
    subtitle: "Add optional background music, or keep narration only.",
    isComplete: () => true,
  },
  {
    id: "review",
    title: "Review",
    subtitle: "Confirm everything, choose variations, then start rendering.",
    isComplete: () => true,
  },
] as const;

function labelFor(
  options: readonly { value: string; title?: string; label?: string }[],
  value: string,
): string {
  const match = options.find((o) => o.value === value);
  return match?.title ?? match?.label ?? value;
}

/** One-line music description for the review summary (AI brief > library track). */
function musicSummary(state: WizardState): string {
  const prompt = state.musicPrompt?.trim();
  if (prompt) {
    const providerName = state.bgmProvider ? ` (${state.bgmProvider})` : "";
    return `AI-generated${providerName}: ${prompt}`;
  }
  return state.musicLabel ?? "No background music";
}

/** Builds the API request from wizard state. Assumes required fields are set. */
export function buildRequest(state: WizardState): JobCreateRequest {
  // BRING YOUR OWN VOICEOVER: when the creator uploaded their own narration, that
  // audio replaces TTS — send no `voice_name`/`voice_id` and let the backend
  // transcribe the uploaded audio for captions + avatar lip-sync.
  const useOwnVoiceover = state.useOwnVoiceover && Boolean(state.voiceoverKey);

  const params: ReelForgeParams = {
    video_subject: state.videoSubject.trim(),
    voice_name: useOwnVoiceover ? "" : `elevenlabs:${state.voiceId ?? ""}`,
    avatar_id: state.avatarId ?? "",
    avatar_provider: "heygen",
    caption_style: state.captionStyle,
    layout: state.layout,
    aspect: "9:16",
    language: state.language,
    target_duration_s: state.targetDurationS,
    platforms: [],
    screen_recording_key: state.screenRecordingKey ?? "",
  };

  const script = state.prompt.trim();
  const withScript: ReelForgeParams = script
    ? { ...params, video_script: script }
    : params;

  // AI background music takes precedence over a library track (the two are
  // mutually exclusive in the UI, but guard here too). When a brief is present,
  // send `music_prompt` (+ optional `bgm_provider`) and omit `music_id`.
  const musicPrompt = state.musicPrompt?.trim() ?? "";
  const useAiMusic = musicPrompt.length > 0;

  return {
    params: withScript,
    broll_intro_key: state.brollIntroKey ?? undefined,
    avatar_id: state.avatarId ?? undefined,
    voice_id: useOwnVoiceover ? undefined : (state.voiceId ?? undefined),
    // BYOV: the creator's own uploaded narration audio (R2 key). Mutually
    // exclusive with `voice_id` above.
    voiceover_key: useOwnVoiceover ? (state.voiceoverKey ?? undefined) : undefined,
    // Batch fan-out + creator-studio extras (§5.2). `caption_style` is sent
    // top-level too so it takes precedence at the controller; `music_id` is
    // only included when a track was chosen.
    variants: state.variants,
    caption_style: state.captionStyle,
    music_id: useAiMusic ? undefined : (state.musicId ?? undefined),
    music_prompt: useAiMusic ? musicPrompt : undefined,
    // Omit `bgm_provider` when auto-selecting the first enabled provider.
    bgm_provider: useAiMusic ? (state.bgmProvider ?? undefined) : undefined,
    // Charge to a workspace's SHARED pool when one is selected; otherwise the
    // caller's personal credits (the backend enforces membership).
    workspace_id: state.workspaceId ?? undefined,
    // Opt-in retention edit: strip dead air from the recording before compose.
    // Omit when off so the payload stays identical to the pre-feature shape.
    auto_tighten: state.autoTighten ? true : undefined,
    // Opt-in editing-polish passes (all default-off + degrade-safe backend-side).
    // Each is omitted when disabled so the payload is byte-for-byte unchanged
    // unless the creator turns it on.
    auto_zoom: state.autoZoom ? true : undefined,
    camera_motion:
      state.cameraMotion !== "none" ? state.cameraMotion : undefined,
    remove_bg: state.removeBg ? true : undefined,
    // PAY-AS-YOU-GO (optional): when a generation profile + signed quote are
    // selected, fund the job from the wallet. Both are omitted otherwise so the
    // payload is byte-for-byte the classic credit-path shape.
    generation_profile_id: state.generationProfileId ?? undefined,
    quote:
      state.generationProfileId && state.generationQuote
        ? state.generationQuote
        : undefined,
    // Effects Mix: only sent when the creator selected at least one VFX preset.
    effects: state.effects.length > 0 ? state.effects : undefined,
  };
}

/**
 * The first format this wizard's choices need that the server has locked, or
 * `null`. Mirrors the server's pre-debit `format_locked` check.
 */
export function wizardFormatLock(
  state: WizardState,
  availability: FormatAvailability | null,
): LockedFormat | null {
  const useOwnVoiceover = state.useOwnVoiceover && Boolean(state.voiceoverKey);
  return firstLock(
    availability,
    requiredReelFormats({
      layout: state.layout,
      hasTypedScript: state.prompt.trim().length > 0,
      hasVoiceover: useOwnVoiceover,
      hasScreenRecording: Boolean(state.screenRecordingKey),
      hasVoice: !useOwnVoiceover,
      premiumVoiceUsable:
        availability !== null && lockFor(availability, "premium_voice") === null,
    }),
  );
}

/** Select the accepted server-owned destination without trusting IDs as paths. */
export function routeForCreateResult(result: JobCreateResult): string {
  const isBatch = Boolean(result.batch_id) || (result.job_ids?.length ?? 0) > 1;
  if (isBatch && result.batch_id) {
    return `/batch/${encodeURIComponent(result.batch_id)}`;
  }
  const firstId = result.job_ids?.[0] ?? result.job_id;
  return `/jobs/${encodeURIComponent(firstId)}`;
}

/** Projects the current wizard choices into a saveable preset ("brand kit"). */
function wizardPresetConfig(state: WizardState): PresetConfig {
  return {
    avatar_id: state.avatarId ?? undefined,
    voice_id: state.voiceId ?? undefined,
    voice_label: state.voiceLabel ?? undefined,
    layout: state.layout,
    caption_style: state.captionStyle,
    music_id: state.musicId ?? undefined,
    language: state.language,
  };
}

/** Apply a curated template's fields onto the wizard state (immutably). */
function templatePatch(
  template: Template,
  current: WizardState,
): Partial<WizardState> {
  return {
    templateId: template.id,
    videoSubject: template.video_subject ?? current.videoSubject,
    prompt: template.prompt_scaffold ?? current.prompt,
    layout: coerceLayout(String(template.layout), current.layout),
    captionStyle: template.caption_style || current.captionStyle,
    captionStyleLabel: null,
    language: coerceLanguage(String(template.language), current.language),
    targetDurationS:
      typeof template.target_duration_s === "number" &&
      template.target_duration_s > 0
        ? template.target_duration_s
        : current.targetDurationS,
  };
}

/**
 * The reel-creation wizard. Collects upload, script, avatar, voice, layout, and
 * caption choices across steps, then POSTs `/jobs` and routes to the job status
 * page. State is updated immutably; no field is mutated in place.
 */
export function Wizard() {
  const router = useRouter();
  const getApiToken = useApiToken();
  const capabilityState = useGenerationCapabilities();
  const generationAllowed =
    capabilityState.capabilities?.generation.reels === true;

  const [state, setState] = React.useState<WizardState>(DEFAULT_WIZARD_STATE);
  const [stepIndex, setStepIndex] = React.useState(0);
  const [submitting, setSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const [submitNeedsCredits, setSubmitNeedsCredits] = React.useState(false);
  const pendingCreate = React.useRef<
    { fingerprint: string; idempotencyKey: string } | undefined
  >(undefined);
  const createInFlight = React.useRef(false);

  const { availability } = useFormatAvailability();
  const avatarLock = lockFor(availability, "avatar_reel");
  const scriptLock = lockFor(availability, "generated_script");
  const premiumVoiceLock = lockFor(availability, "premium_voice");
  const formatLock = wizardFormatLock(state, availability);

  const step = STEPS[stepIndex]!;
  const isLastStep = stepIndex === STEPS.length - 1;
  // Without a script LLM the creator must type the script themselves.
  const scriptRequired = step.id === "script" && scriptLock !== null;
  const canProceed =
    step.isComplete(state) && (!scriptRequired || state.prompt.trim().length > 0);

  const patch = React.useCallback((update: Partial<WizardState>) => {
    setState((prev) => ({ ...prev, ...update }));
  }, []);

  // SPARK handoff: if the user clicked "Make this" on an idea, pre-fill the
  // script/layout/caption/language fields once, then jump past the template
  // step to the upload step (a recording is still required). Single-use.
  const prefillApplied = React.useRef(false);
  React.useEffect(() => {
    if (prefillApplied.current) return;
    prefillApplied.current = true;
    const prefill = takeSparkPrefill();
    if (!prefill) return;
    patch({
      videoSubject: prefill.videoSubject,
      prompt: prefill.prompt,
      layout: prefill.layout,
      captionStyle: prefill.captionStyle,
      captionStyleLabel: null,
      language: prefill.language,
      templateId: null,
    });
    setStepIndex(1);
  }, [patch]);

  // Catalog deep links: `/new?template=`, `/new?avatar=` (or `avatar_id`),
  // `/new?voice=` (or `voice_id`), `/new?subject=` preselect the user's
  // choice. Applied once.
  const searchParams = useSearchParams();
  const [deepLinkNotice, setDeepLinkNotice] = React.useState<string | null>(null);
  const deepLinkApplied = React.useRef(false);
  React.useEffect(() => {
    if (deepLinkApplied.current) return;
    deepLinkApplied.current = true;
    const param = (name: string): string =>
      (searchParams?.get(name) ?? "").trim();
    const templateId = param("template");
    const avatarId = param("avatar") || param("avatar_id");
    const voiceId = param("voice") || param("voice_id");
    // Promoted clip drafts (studio clips) hand over their subject line.
    const subject = param("subject");

    if (subject) patch({ videoSubject: subject, templateId: null });
    if (avatarId) patch({ avatarId });
    if (voiceId) {
      patch({ voiceId, voiceLabel: null, useOwnVoiceover: false });
    }
    if (!templateId) {
      if (avatarId || voiceId || subject) setStepIndex(1);
      return;
    }

    void (async () => {
      try {
        const token = await getApiToken();
        const templates = await listTemplates({ token });
        const match = templates.find((t) => t.id === templateId);
        if (!match) {
          setDeepLinkNotice(
            "That template is no longer available — pick another below or start from scratch.",
          );
          return;
        }
        setState((prev) => ({ ...prev, ...templatePatch(match, prev) }));
        setStepIndex(1);
      } catch (err) {
        setDeepLinkNotice(
          err instanceof ApiError
            ? friendlyErrorMessage(err, "Could not load the selected template.")
            : "Could not load the selected template. Pick it again below.",
        );
      }
    })();
  }, [getApiToken, patch, searchParams]);

  React.useEffect(() => {
    const attachment = loadBrollAttachment();
    if (!attachment) return;
    patch({
      brollIntroKey: attachment.key,
      brollPreviewUrl: attachment.resultUrl || null,
    });
  }, [patch]);

  const goNext = React.useCallback(() => {
    setStepIndex((i) => Math.min(i + 1, STEPS.length - 1));
  }, []);

  const goBack = React.useCallback(() => {
    setStepIndex((i) => Math.max(i - 1, 0));
  }, []);

  const handleSubmit = React.useCallback(async () => {
    if (!generationAllowed) {
      setSubmitError(
        capabilityState.error ||
          "Reel generation is not available for this account right now.",
      );
      return;
    }
    if (createInFlight.current) return;
    if (formatLock) {
      setSubmitNeedsCredits(false);
      setSubmitError(formatLockedMessage(formatLock));
      return;
    }
    const request = buildRequest(state);
    const fingerprint = JSON.stringify(request);
    if (pendingCreate.current?.fingerprint !== fingerprint) {
      pendingCreate.current = {
        fingerprint,
        idempotencyKey: createIdempotencyKey(),
      };
    }
    const commandKey = pendingCreate.current.idempotencyKey;
    createInFlight.current = true;
    setSubmitError(null);
    setSubmitNeedsCredits(false);
    setSubmitting(true);
    try {
      const token = await getApiToken();
      const result = await createJob(request, {
        token,
        idempotencyKey: commandKey,
      });
      pendingCreate.current = undefined;
      clearBrollAttachment();
      router.push(routeForCreateResult(result));
    } catch (err) {
      const lock = formatLockOf(err);
      const outOfCredits = isCreditShortfall(err);
      const message = lock
        ? formatLockedMessage(lock)
        : outOfCredits
          ? "You're out of credits. Top up with a credit pack to render this reel — your settings are kept."
          : friendlyErrorMessage(err, "Something went wrong creating your reel. Please try again.");
      setSubmitNeedsCredits(outOfCredits);
      setSubmitError(message);
      createInFlight.current = false;
      setSubmitting(false);
    }
  }, [capabilityState.error, formatLock, generationAllowed, getApiToken, router, state]);

  if (capabilityState.loading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          Checking reel generation availability…
        </CardContent>
      </Card>
    );
  }

  if (!generationAllowed) {
    return (
      <Card>
        <CardContent className="py-8">
          <p className="font-medium">Reel generation is not available for this account.</p>
          <p className="mt-2 text-sm text-muted-foreground" role="alert">
            {capabilityState.error ||
              "This format is not available for this account right now."}
          </p>
          <GenerationUnavailableCta />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[220px_1fr]">
      {/* Stepper */}
      <nav aria-label="Progress" className="lg:sticky lg:top-6 lg:self-start">
        <ol className="flex gap-2 overflow-x-auto lg:flex-col lg:gap-1">
          {STEPS.map((s, i) => {
            const done = i < stepIndex;
            const current = i === stepIndex;
            return (
              <li key={s.id} className="shrink-0">
                <button
                  type="button"
                  // Only allow jumping back to visited steps.
                  disabled={i > stepIndex}
                  onClick={() => setStepIndex(i)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors",
                    "disabled:cursor-not-allowed disabled:opacity-50",
                    current
                      ? "bg-primary/15 font-medium text-primary"
                      : "text-muted-foreground hover:bg-secondary/50",
                  )}
                >
                  <span
                    className={cn(
                      "flex size-5 shrink-0 items-center justify-center rounded-full border text-xs",
                      current && "border-primary text-primary",
                      done && "border-success bg-success text-success-foreground",
                      !current && !done && "border-border",
                    )}
                  >
                    {done ? <Check className="size-3" aria-hidden /> : i + 1}
                  </span>
                  <span className="whitespace-nowrap">{s.title}</span>
                </button>
              </li>
            );
          })}
        </ol>
      </nav>

      {/* Step content */}
      <div>
        {avatarLock && (
          <FormatNotice className="mb-6">
            {`${avatarLock.label}. ${lockedOptionReason(avatarLock)} `}
            <Link
              href="/create/advanced"
              className="font-medium text-primary underline underline-offset-4"
            >
              Make a captioned reel from your own narration
            </Link>{" "}
            instead. It needs no avatar.
          </FormatNotice>
        )}
        {deepLinkNotice && (
          <p
            role="status"
            className="mb-6 flex items-center gap-2 rounded-lg border border-border bg-muted/40 p-3 text-sm text-muted-foreground"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            {deepLinkNotice}
          </p>
        )}
        {state.brollIntroKey && (
          <div className="mb-6 flex items-center gap-4 rounded-lg border border-primary/30 bg-primary/5 p-3">
            {state.brollPreviewUrl ? (
              <video
                className="h-20 w-12 rounded bg-black object-cover"
                src={state.brollPreviewUrl}
                muted
                playsInline
                preload="metadata"
                aria-label="Attached AI B-roll preview"
              />
            ) : null}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">AI B-roll intro attached</p>
              <p className="truncate font-mono text-xs text-muted-foreground">
                {state.brollIntroKey}
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                clearBrollAttachment();
                patch({ brollIntroKey: null, brollPreviewUrl: null });
              }}
            >
              Remove
            </Button>
          </div>
        )}
        <header className="mb-6">
          <p className="text-xs font-medium uppercase tracking-wide text-primary">
            Step {stepIndex + 1} of {STEPS.length}
          </p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">
            {step.title}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{step.subtitle}</p>
        </header>

        <Card>
          <CardContent className="pt-6">
            {step.id === "template" && (
              <TemplateGallery
                value={state.templateId}
                onApply={(template) => patch(templatePatch(template, state))}
                onClear={() => patch({ templateId: null })}
              />
            )}

            {step.id === "upload" && (
              <UploadDropzone
                value={
                  state.screenRecordingKey && state.screenRecordingUrl
                    ? {
                        key: state.screenRecordingKey,
                        url: state.screenRecordingUrl,
                        name: state.screenRecordingName ?? "recording",
                      }
                    : null
                }
                onUploaded={(rec) =>
                  patch({
                    screenRecordingKey: rec.key,
                    screenRecordingUrl: rec.url,
                    screenRecordingName: rec.name,
                  })
                }
                onClear={() =>
                  patch({
                    screenRecordingKey: null,
                    screenRecordingUrl: null,
                    screenRecordingName: null,
                  })
                }
              />
            )}

            {step.id === "script" && scriptLock && (
              <FormatNotice>
                {`${scriptLock.label}. ${lockedOptionReason(scriptLock)} Type your own script to continue.`}
              </FormatNotice>
            )}

            {step.id === "script" && (
              <ScriptPromptField
                value={{
                  videoSubject: state.videoSubject,
                  prompt: state.prompt,
                  language: state.language,
                  targetDurationS: state.targetDurationS,
                }}
                onChange={patch}
              />
            )}

            {step.id === "avatar" && (
              <AvatarPicker
                value={state.avatarId}
                onSelect={(avatarId) => patch({ avatarId })}
              />
            )}

            {step.id === "voice" && premiumVoiceLock && !state.useOwnVoiceover && (
              <FormatNotice>
                ElevenLabs voices are not set up on this server, so the reel is
                narrated with a free voice instead. Upload your own voiceover to
                use your voice.
              </FormatNotice>
            )}

            {step.id === "voice" && (
              <VoiceStep
                voiceId={state.voiceId}
                onSelectVoice={(voiceId, voiceLabel) =>
                  patch({ voiceId, voiceLabel })
                }
                useOwnVoiceover={state.useOwnVoiceover}
                onModeChange={(useOwnVoiceover) => patch({ useOwnVoiceover })}
                voiceover={
                  state.voiceoverKey && state.voiceoverUrl
                    ? {
                        key: state.voiceoverKey,
                        url: state.voiceoverUrl,
                        name: state.voiceoverName ?? "Voiceover",
                      }
                    : null
                }
                onVoiceoverUploaded={(vo) =>
                  patch({
                    voiceoverKey: vo.key,
                    voiceoverUrl: vo.url,
                    voiceoverName: vo.name,
                  })
                }
                onVoiceoverClear={() =>
                  patch({
                    voiceoverKey: null,
                    voiceoverUrl: null,
                    voiceoverName: null,
                  })
                }
              />
            )}

            {step.id === "layout" && (
              <LayoutPicker
                value={state.layout}
                onSelect={(layout) => patch({ layout })}
                avatarLock={avatarLock}
              />
            )}

            {step.id === "captions" && (
              <CaptionStylePicker
                value={state.captionStyle}
                onSelect={(captionStyle, captionStyleLabel) =>
                  patch({ captionStyle, captionStyleLabel })
                }
              />
            )}

            {step.id === "music" && (
              <MusicPicker
                value={state.musicId}
                // Picking a library track clears any in-progress AI brief so a
                // job only ever carries one of `music_id` / `music_prompt`.
                onSelect={(musicId, musicLabel) =>
                  patch({
                    musicId,
                    musicLabel,
                    musicPrompt: null,
                    bgmProvider: null,
                  })
                }
                prompt={state.musicPrompt}
                provider={state.bgmProvider}
                // Writing an AI brief clears any selected library track.
                onGenerateChange={(musicPrompt, bgmProvider) =>
                  patch({
                    musicPrompt,
                    bgmProvider,
                    musicId: musicPrompt ? null : state.musicId,
                    musicLabel: musicPrompt ? null : state.musicLabel,
                  })
                }
              />
            )}

            {step.id === "review" && (
              <div className="space-y-6">
                <ReviewSummary state={state} />
                <div>
                  <h3 className="mb-3 text-sm font-semibold">Variations</h3>
                  <VariantsSelector
                    value={state.variants}
                    onChange={(variants) => patch({ variants })}
                  />
                </div>
                <div className="border-t border-border pt-4">
                  <h3 className="mb-3 text-sm font-semibold">Pacing</h3>
                  <AutoTightenToggle
                    checked={state.autoTighten}
                    onChange={(autoTighten) => patch({ autoTighten })}
                  />
                </div>
                <div className="border-t border-border pt-4">
                  <h3 className="mb-1 text-sm font-semibold">Editing polish</h3>
                  <p className="mb-3 text-xs text-muted-foreground">
                    Optional finishing passes on your recording. Each is off by
                    default and safely skipped if it can’t be applied.
                  </p>
                  <EditingPolishSection
                    autoZoom={state.autoZoom}
                    onAutoZoomChange={(autoZoom) => patch({ autoZoom })}
                    cameraMotion={state.cameraMotion}
                    onCameraMotionChange={(cameraMotion) =>
                      patch({ cameraMotion })
                    }
                    removeBg={state.removeBg}
                    onRemoveBgChange={(removeBg) => patch({ removeBg })}
                  />
                </div>
                <div className="border-t border-border pt-4">
                  <h3 className="mb-3 text-sm font-semibold">Billing</h3>
                  <ChargeToSelector
                    value={state.workspaceId}
                    onChange={(workspaceId) => patch({ workspaceId })}
                  />
                </div>
                <ProfilePicker
                  value={state.generationProfileId}
                  onChange={(generationProfileId, generationQuote) =>
                    patch({ generationProfileId, generationQuote })
                  }
                />
                <EffectsPicker
                  cameraMotion={state.cameraMotion}
                  effects={state.effects}
                  onChange={(cameraMotion, effects) =>
                    patch({
                      cameraMotion: cameraMotion as WizardState["cameraMotion"],
                      effects,
                    })
                  }
                />
                <div className="border-t border-border pt-4">
                  <p className="mb-2 text-sm text-muted-foreground">
                    Reuse this look on future reels.
                  </p>
                  <SavePresetButton config={wizardPresetConfig(state)} />
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {submitError && (
          <p
            role="alert"
            className="mt-4 flex items-center gap-2 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            {submitError}
            {submitNeedsCredits && (
              <Link
                href="/wallet/plans"
                className="ml-1 shrink-0 font-medium text-primary underline underline-offset-4"
              >
                View credit packs
              </Link>
            )}
          </p>
        )}

        {isLastStep && formatLock && !submitError && (
          <FormatNotice className="mt-4">{formatLockedMessage(formatLock)}</FormatNotice>
        )}

        {/* Nav controls */}
        <div className="mt-6 flex items-center justify-between">
          <Button
            type="button"
            variant="ghost"
            onClick={goBack}
            disabled={stepIndex === 0 || submitting}
          >
            <ArrowLeft /> Back
          </Button>

          {isLastStep ? (
            <Button
              type="button"
              onClick={handleSubmit}
              disabled={submitting || !generationAllowed || formatLock !== null}
            >
              {submitting ? (
                <>
                  <Loader2 className="animate-spin" /> Creating…
                </>
              ) : (
                <>
                  <Sparkles /> Create reel
                </>
              )}
            </Button>
          ) : (
            <Button type="button" onClick={goNext} disabled={!canProceed}>
              Continue <ArrowRight />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function createIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `web-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// ---------------------------------------------------------------------------
// Review summary
// ---------------------------------------------------------------------------

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border py-2.5 last:border-b-0">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="max-w-[60%] truncate text-right text-sm font-medium">
        {value}
      </dd>
    </div>
  );
}

function ReviewSummary({ state }: { state: WizardState }) {
  return (
    <dl>
      <SummaryRow
        label="Screen recording"
        value={state.screenRecordingName ?? "—"}
      />
      <SummaryRow label="Subject" value={state.videoSubject.trim() || "—"} />
      <SummaryRow
        label="Custom script"
        value={state.prompt.trim() ? "Provided" : "AI-generated"}
      />
      <SummaryRow
        label="Language"
        value={labelFor(LANGUAGE_OPTIONS, state.language)}
      />
      <SummaryRow
        label="Target duration"
        value={`${state.targetDurationS}s`}
      />
      <SummaryRow label="Avatar" value={state.avatarId ?? "—"} />
      <SummaryRow
        label="Voice"
        value={
          state.useOwnVoiceover
            ? `Your own voiceover${
                state.voiceoverName ? ` (${state.voiceoverName})` : ""
              }`
            : (state.voiceLabel ?? state.voiceId ?? "—")
        }
      />
      {state.useOwnVoiceover && (
        <SummaryRow label="Caption text" value="Auto-generated from your audio" />
      )}
      <SummaryRow label="Layout" value={labelFor(LAYOUT_OPTIONS, state.layout)} />
      <SummaryRow
        label="Captions"
        value={
          state.captionStyleLabel ??
          labelFor(CAPTION_STYLE_OPTIONS, state.captionStyle)
        }
      />
      <SummaryRow label="Music" value={musicSummary(state)} />
      <SummaryRow
        label="Variations"
        value={
          state.variants > 1 ? `${state.variants} variations` : "Single reel"
        }
      />
      <SummaryRow
        label="Auto-tighten"
        value={state.autoTighten ? "On — remove dead air" : "Off"}
      />
      <SummaryRow
        label="Auto-zoom"
        value={state.autoZoom ? "On — scene punch-ins" : "Off"}
      />
      <SummaryRow
        label="Camera motion"
        value={labelFor(CAMERA_MOTION_OPTIONS, state.cameraMotion)}
      />
      <SummaryRow
        label="Remove background"
        value={state.removeBg ? "On — matte avatar" : "Off"}
      />
      <SummaryRow label="Aspect ratio" value="9:16" />
      <SummaryRow
        label="AI B-roll intro"
        value={state.brollIntroKey ? "Attached" : "None"}
      />
    </dl>
  );
}

/** Neutral notice for a format the server cannot produce (not an error). */
function FormatNotice({
  children,
  className,
}: Readonly<{ children: React.ReactNode; className?: string }>) {
  return (
    <p
      role="status"
      className={cn(
        "mb-4 flex items-start gap-2 rounded-lg border border-border bg-muted/40 p-3 text-sm text-muted-foreground",
        className,
      )}
    >
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}
