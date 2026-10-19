"use client";

/**
 * The default create flow for new users: one box (topic or product/page
 * link), one preset choice, one button. It starts three reel variants with
 * different opening hooks on the existing `POST /jobs` pipeline and hands off
 * to `/create/results`, which tracks each variant live. Each run is registered
 * as a 1-body/N-hooks experiment so the remake-winner loop tracks it.
 *
 * The faceless story preset needs no presenter: the API narrates the script
 * with the chosen voice over looping background footage.
 *
 * Presenter, voice, background and language have working defaults pulled
 * from the live catalogs; they sit behind a collapsed "Presenter and voice"
 * section so the first run is a single click.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowRight, Coins, Link2, Loader2, RefreshCw, Type } from "lucide-react";
import {
  ApiError,
  createJob,
  getMe,
  ingestUrl,
  listAvatars,
  listBackgrounds,
  listVoices,
} from "@/lib/api";
import type { Avatar, BackgroundClip, Language, Voice } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { LANGUAGE_OPTIONS, coerceLanguage } from "@/components/wizard/types";
import { GenerationUnavailableCta } from "@/components/marketing/GenerationUnavailableCta";
import { useGenerationCapabilities } from "@/lib/use-generation-capabilities";
import { BuyCredits, runSizeFor, signUpHref, unlockHref, useWebAccess } from "@/src/shared/access";
import { PlanUpsell } from "@/src/features/plans";
import { cn } from "@/lib/utils";
import {
  CLASSIC_PRESETS,
  CREATE_PRESETS,
  STYLE_PRESETS,
  VARIANT_COUNT,
  buildJobRequest,
  buildRunRegistration,
  defaultPresetFor,
  findPreset,
  parseSource,
  resolvePreset,
  pickBackground,
  planLinkVariants,
  planStyleVariants,
  resultsHref,
  storySubject,
  topicRunVariants,
  type CreatePreset,
  type LinkVariantPlan,
  type PageContent,
  type PresetId,
} from "./plan";
import { detectLinkKind } from "./link-kind";
import { registerRun, writeStyleHooks } from "./run-api";
import { saveRun, type RunVariantMeta } from "./run-store";
import {
  firstLock,
  formatLockOf,
  formatLockedMessage,
  lockFor,
  lockedOptionReason,
  requiredReelFormats,
  useFormatAvailability,
  type FormatAvailability,
  type LockedFormat,
} from "@/src/shared/launch";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface OneFlowCreateProps {
  /** Prefill from `/create?q=` (the landing hero submits here). */
  readonly initialInput?: string;
  /** Prefill from `/create?preset=`. */
  readonly initialPreset?: string;
  /**
   * `/create?auto=1` (sent after sign-up + card check with the link the
   * visitor pasted on the landing page): start the renders as soon as the
   * defaults load, with no further questions.
   */
  readonly autoStart?: boolean;
}

interface Catalog {
  readonly avatars: readonly Avatar[];
  readonly voices: readonly Voice[];
  readonly backgrounds: readonly BackgroundClip[];
}

type CatalogState =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly catalog: Catalog };

type SubmitPhase = "idle" | "reading" | "starting";

/** Narration voice used when the voice catalog can't load (curated "Adam"). */
const FALLBACK_VOICES: readonly Voice[] = [
  { voice_id: "pNInz6obpgDQGcFmaJgB", name: "Default voice" } as Voice,
];

/** The first-party loops every server ships (packaged in the worker image). */
const FALLBACK_BACKGROUNDS: readonly BackgroundClip[] = [
  { id: "block-runner", available: true } as BackgroundClip,
  { id: "sand-slice", available: true } as BackgroundClip,
  { id: "marble-loop", available: true } as BackgroundClip,
];

function voiceIdOf(voice: Voice): string {
  const raw = voice.voice_id ?? (voice as { id?: unknown }).id;
  return typeof raw === "string" ? raw : "";
}

function avatarLabel(avatar: Avatar | undefined): string {
  if (!avatar) return "";
  return avatar.display_name || avatar.name || avatar.avatar_id;
}

function voiceLabel(voice: Voice | undefined): string {
  if (!voice) return "";
  return voice.name || voiceIdOf(voice);
}

/** The avatar's paired voice when the catalog carries it, else the first voice. */
function defaultVoiceFor(avatar: Avatar | undefined, voices: readonly Voice[]): string {
  const paired = (avatar?.voice_name ?? "").replace(/^elevenlabs:/, "");
  if (paired && voices.some((voice) => voiceIdOf(voice) === paired)) return paired;
  return voices.map(voiceIdOf).find(Boolean) ?? "";
}

/**
 * The first format a preset needs that the server has locked. Link runs send
 * the scripts they write; topic runs need the script LLM. Every preset
 * narrates with a TTS voice (`elevenlabs:` falls back to a free voice).
 */
function presetLock(
  presetId: PresetId,
  isLink: boolean,
  availability: FormatAvailability | null,
): LockedFormat | null {
  const preset = resolvePreset(presetId);
  return firstLock(
    availability,
    requiredReelFormats({
      layout: preset.layout,
      hasTypedScript: isLink,
      hasVoice: true,
      premiumVoiceUsable:
        availability !== null && lockFor(availability, "premium_voice") === null,
    }),
  );
}

function friendlyError(err: unknown): string {
  const lock = formatLockOf(err);
  if (lock) return formatLockedMessage(lock);
  if (err instanceof ApiError) {
    if (err.status === 402) {
      return "You don't have enough credits for this run. Each reel uses 1 credit.";
    }
    if (err.status === 429) {
      return "You've started a lot of renders in the last hour. Wait a few minutes and try again.";
    }
    if (err.status === 422 || err.status === 400) {
      return friendlyErrorMessage(err, "That input couldn't be used. Check it and try again.");
    }
    if (err.status === 503) {
      return "Rendering is temporarily unavailable. Please try again in a few minutes.";
    }
    return friendlyErrorMessage(err);
  }
  if (err instanceof Error) return friendlyErrorMessage(err);
  return "Something went wrong. Please try again.";
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function OneFlowCreate({ initialInput = "", initialPreset, autoStart = false }: OneFlowCreateProps) {
  const router = useRouter();
  const access = useWebAccess();
  const getApiToken = access.getToken;
  const { capabilities, loading: capsLoading, error: capsError } = useGenerationCapabilities();

  const [input, setInput] = React.useState(initialInput);
  const parsed = parseSource(input);
  const initialPresetId = findPreset(initialPreset)?.id;
  const [presetId, setPresetId] = React.useState<PresetId>(
    initialPresetId ?? defaultPresetFor(parseSource(initialInput)?.kind ?? "topic"),
  );
  const [presetTouched, setPresetTouched] = React.useState(Boolean(initialPresetId));
  const [language, setLanguage] = React.useState<Language>("auto");
  const [avatarId, setAvatarId] = React.useState("");
  const [voiceId, setVoiceId] = React.useState("");
  const [catalog, setCatalog] = React.useState<CatalogState>({ status: "loading" });
  const [catalogNonce, setCatalogNonce] = React.useState(0);
  const [credits, setCredits] = React.useState<number | null>(null);
  const [phase, setPhase] = React.useState<SubmitPhase>("idle");
  const [error, setError] = React.useState("");
  const [outOfCredits, setOutOfCredits] = React.useState(false);
  const formRef = React.useRef<HTMLFormElement>(null);
  const autoFired = React.useRef(false);

  const { availability } = useFormatAvailability();
  const isLink = parsed?.kind === "link";

  const admitted = Boolean(capabilities?.generation?.reels);
  const ready = access.state.status === "ready" && !capsLoading && admitted;

  // Sign-up and the $1 card check come first; bring the visitor back here
  // (with what they typed) afterwards.
  const accessStatus = access.state.status;
  React.useEffect(() => {
    if (accessStatus !== "signed-out" && accessStatus !== "locked") return;
    const query: Record<string, string> = initialInput ? { q: initialInput, auto: "1" } : {};
    if (initialPresetId) query.preset = initialPresetId;
    const back = `/create?${new URLSearchParams(query).toString()}`.replace(/\?$/, "");
    router.replace(accessStatus === "signed-out" ? signUpHref(back) : unlockHref(back));
  }, [accessStatus, initialInput, initialPresetId, router]);

  // Follow the input: a link suggests the product-ad preset, a topic the
  // presenter, until the creator picks a preset themselves.
  const parsedKind = parsed?.kind;
  React.useEffect(() => {
    if (presetTouched || !parsedKind) return;
    setPresetId(defaultPresetFor(parsedKind));
  }, [parsedKind, presetTouched]);

  // No presenter available (e.g. the avatar provider is down): until the
  // creator picks a format, use a faceless style so the run can still start.
  const noPresenters = catalog.status === "ready" && catalog.catalog.avatars.length === 0;
  React.useEffect(() => {
    if (presetTouched || !noPresenters || !resolvePreset(presetId).needsPresenter) return;
    setPresetId(isLink ? "gameplay_split" : "faceless");
  }, [noPresenters, presetId, presetTouched, isLink]);

  // Until the creator picks one, move off a preset this server can't render
  // onto the first one it can.
  React.useEffect(() => {
    if (presetTouched || !presetLock(presetId, isLink, availability)) return;
    const open = CREATE_PRESETS.find((p) => !presetLock(p.id, isLink, availability));
    if (open) setPresetId(open.id);
  }, [availability, isLink, presetId, presetTouched]);

  React.useEffect(() => {
    if (!ready) return;
    let active = true;
    const controller = new AbortController();
    setCatalog({ status: "loading" });
    void (async () => {
      try {
        const token = await getApiToken();
        const options = { token, signal: controller.signal };
        // Each catalog degrades on its own: an unavailable presenter provider
        // must not block the faceless styles, and the pipeline narrates with
        // a default voice / the style's own loop when a list can't load.
        const [avatarsResult, voicesResult, backgroundsResult] = await Promise.allSettled([
          listAvatars(options),
          listVoices(options),
          listBackgrounds(undefined, options),
        ]);
        if (!active) return;
        const avatars = avatarsResult.status === "fulfilled" ? avatarsResult.value : [];
        const voices = voicesResult.status === "fulfilled" ? voicesResult.value : [];
        const backgrounds =
          backgroundsResult.status === "fulfilled" ? backgroundsResult.value : FALLBACK_BACKGROUNDS;
        const usableAvatars = avatars.filter((avatar) => avatar.is_active !== false);
        const listedVoices = (Array.isArray(voices) ? voices : []).filter((v) => voiceIdOf(v));
        const usableVoices = listedVoices.length > 0 ? listedVoices : FALLBACK_VOICES;
        setCatalog({
          status: "ready",
          catalog: { avatars: usableAvatars, voices: usableVoices, backgrounds },
        });
        const firstAvatar = usableAvatars[0];
        setAvatarId((prev) => prev || firstAvatar?.avatar_id || "");
        setVoiceId((prev) => prev || defaultVoiceFor(firstAvatar, usableVoices));
      } catch (err) {
        if (!active || controller.signal.aborted) return;
        setCatalog({ status: "error", message: friendlyError(err) });
      }
    })();
    void (async () => {
      try {
        const token = await getApiToken();
        const me = await getMe({ token, signal: controller.signal });
        if (active) setCredits(me.credits);
      } catch {
        // Non-blocking: the create call itself reports a credit shortfall.
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [ready, getApiToken, catalogNonce]);

  if (access.state.status === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex flex-col items-start gap-4 p-6">
          <p className="flex items-start gap-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {access.state.message}
          </p>
          <Button type="button" variant="outline" size="sm" onClick={access.refresh}>
            <RefreshCw className="size-4" aria-hidden /> Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (access.state.status === "signed-out" || access.state.status === "locked") {
    return (
      <LoadingRow
        label={
          access.state.status === "signed-out"
            ? "Taking you to sign-up…"
            : "Taking you to unlock your free reels…"
        }
      />
    );
  }

  if (access.state.status === "loading" || capsLoading) {
    return <LoadingRow label="Preparing your studio…" />;
  }

  if (capsError || !admitted) {
    return (
      <Card>
        <CardContent className="p-6">
          <p className="text-sm text-muted-foreground">
            Reel rendering isn&apos;t open for this account yet.
          </p>
          <GenerationUnavailableCta />
        </CardContent>
      </Card>
    );
  }

  const preset = resolvePreset(presetId);
  const catalogReady = catalog.status === "ready" ? catalog.catalog : null;
  const backgroundId = catalogReady
    ? pickBackground(catalogReady.backgrounds, preset.preferredBackground)
    : "";
  const needsPresenter = preset.needsPresenter;
  const missing: string[] = [];
  if (catalogReady) {
    if (needsPresenter && catalogReady.avatars.length === 0) missing.push("an AI presenter");
    if (catalogReady.voices.length === 0) missing.push("a narration voice");
    if (!backgroundId) missing.push("background footage");
  }
  // The free first reel (before the card check) is one reel, not a three-hook test.
  const runSize = runSizeFor(access.state.status === "ready" ? access.state.card : null, VARIANT_COUNT);
  const firstReel = runSize < VARIANT_COUNT;
  const notEnoughCredits = credits !== null && credits < runSize;
  const busy = phase !== "idle";
  const selectedLock = presetLock(preset.id, isLink, availability);
  const facelessOpen = presetLock("faceless", isLink, availability) === null;
  const canSubmit =
    selectedLock === null &&
    Boolean(parsed) &&
    Boolean(catalogReady) &&
    missing.length === 0 &&
    (!needsPresenter || Boolean(avatarId)) &&
    Boolean(voiceId) &&
    !notEnoughCredits &&
    !busy;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit || !parsed) return;
    setError("");
    setOutOfCredits(false);
    const startedAt = Date.now();
    const base = {
      layout: preset.layout,
      avatarId,
      voiceId,
      backgroundId,
      language,
      ...(preset.style ? { style: preset.style } : {}),
    };
    try {
      const token = await getApiToken();
      let variants: RunVariantMeta[] = [];
      let notice: string | undefined;

      if (parsed.kind === "topic") {
        setPhase("starting");
        const result = await createJob(
          buildJobRequest({ ...base, subject: parsed.value, variants: runSize }),
          { token },
        );
        // The API assigns each variant its own hook angle and registers the
        // batch as an experiment itself.
        variants = topicRunVariants(result);
      } else {
        setPhase("reading");
        const page = await ingestUrl(parsed.value, { token });
        const subject =
          page.reel_draft?.video_subject || page.content?.title || hostOf(parsed.value);
        const content: PageContent = {
          title: page.content?.title || subject,
          description: page.content?.description ?? "",
          features: page.content?.features ?? [],
        };
        if (preset.scriptMode === "story") {
          // Story styles: the API writes a first-person story about the
          // product from the page, one hook angle per variant.
          setPhase("starting");
          const result = await createJob(
            buildJobRequest({
              ...base,
              subject: storySubject(content, subject),
              variants: runSize,
              sourceUrl: parsed.value,
            }),
            { token },
          );
          variants = topicRunVariants(result);
          saveRun({ source: parsed.kind, input: parsed.value, presetId: preset.id, startedAt, variants });
          router.push(resultsHref(variants.map((variant) => variant.jobId)));
          return;
        }
        const plans = (await planLinkRun(preset, content, language, token)).slice(0, runSize);
        setPhase("starting");
        for (const plan of plans) {
          try {
            const result = await createJob(
              buildJobRequest({
                ...base,
                subject,
                script: plan.script,
                variants: 1,
                hookStyle: plan.angle,
                sourceUrl: parsed.value,
              }),
              { token },
            );
            variants = [...variants, { jobId: result.job_id, angle: plan.angle, hook: plan.hook }];
          } catch (err) {
            // Nothing started yet: surface the error on this page. Otherwise
            // continue to the results with what did start.
            if (variants.length === 0) throw err;
            notice = `${variants.length} of ${runSize} variants started. ${friendlyError(err)}`;
            break;
          }
        }
        // Link the separately started reels into one hook experiment. The
        // reels render either way, so a failure here is reported, not thrown.
        const registration = buildRunRegistration(variants);
        if (registration) {
          try {
            await registerRun(registration, { token });
          } catch (err) {
            const linkNotice = `Your reels are rendering, but they could not be linked for hook tracking: ${friendlyError(err)}`;
            notice = notice ? `${notice} ${linkNotice}` : linkNotice;
          }
        }
      }

      saveRun({
        source: parsed.kind,
        input: parsed.value,
        presetId: preset.id,
        startedAt,
        variants,
        notice,
      });
      router.push(resultsHref(variants.map((variant) => variant.jobId)));
    } catch (err) {
      setError(friendlyError(err));
      setOutOfCredits(err instanceof ApiError && err.status === 402);
      setPhase("idle");
    }
  };

  return (
    <form ref={formRef} onSubmit={handleSubmit} className="space-y-6" aria-busy={busy}>
      {autoStart && canSubmit && !autoFired.current && (
        <AutoSubmit
          onFire={() => {
            autoFired.current = true;
            formRef.current?.requestSubmit();
          }}
        />
      )}
      <div>
        <label htmlFor="one-flow-input" className="sr-only">
          What is the reel about?
        </label>
        <div className="relative">
          <span className="pointer-events-none absolute left-3 top-3.5 text-muted-foreground">
            {parsed?.kind === "link" ? (
              <Link2 className="size-4" aria-hidden />
            ) : (
              <Type className="size-4" aria-hidden />
            )}
          </span>
          <textarea
            id="one-flow-input"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            rows={2}
            maxLength={600}
            placeholder="Paste any link (your site, app, a TikTok or YouTube video) or type a topic"
            className="w-full resize-none rounded-md border border-input bg-background py-3 pl-9 pr-3 text-base shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            disabled={busy}
            autoFocus={!initialInput}
          />
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground" aria-live="polite">
          {parsed?.kind === "link"
            ? detectLinkKind(parsed.value).label
            : parsed
              ? firstReel
                ? "Your free first reel. After it, a $1 card check unlocks three hook versions per run."
                : "Three versions, each opening with a different hook."
              : "Any link works: your site, your app, or a post you love."}
        </p>
      </div>

      <StylePicker
        presets={STYLE_PRESETS}
        selectedId={preset.id}
        disabled={busy}
        lockOf={(id) => presetLock(id, isLink, availability)}
        onPick={(id) => {
          setPresetId(id);
          setPresetTouched(true);
        }}
      />

      {catalog.status === "loading" && <LoadingRow label="Loading presenters and voices…" />}
      {catalog.status === "error" && (
        <div className="flex flex-wrap items-center gap-3 text-sm text-destructive">
          <AlertCircle className="size-4" aria-hidden /> {catalog.message}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setCatalogNonce((n) => n + 1)}
          >
            <RefreshCw className="size-4" aria-hidden /> Retry
          </Button>
        </div>
      )}

      {catalogReady && missing.length > 0 && (
        <Card className="border-amber-500/40 bg-amber-500/5">
          <CardContent className="space-y-2 p-4 text-sm">
            <p>
              This server doesn&apos;t have {missing.join(", ")} set up yet, so this
              flow can&apos;t render right now.
            </p>
            {missing.length === 1 && missing[0] === "an AI presenter" && facelessOpen ? (
              <>
                <p className="text-muted-foreground">
                  The faceless story format needs no presenter: a narrator voice
                  reads the script over background footage.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setPresetId("faceless");
                    setPresetTouched(true);
                  }}
                >
                  Use the faceless story <ArrowRight className="size-4" aria-hidden />
                </Button>
              </>
            ) : (
              <>
                <p className="text-muted-foreground">
                  You can still make a captioned reel from your own narration, which
                  needs no presenter or voice provider.
                </p>
                <Button asChild variant="outline" size="sm">
                  <Link href="/create/advanced">
                    Narrate it yourself <ArrowRight className="size-4" aria-hidden />
                  </Link>
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* Format, presenter, voice and language all have working defaults, so
          they stay folded away: the first run is one box and one button. */}
      <details className="rounded-lg border border-border p-3 text-sm">
        <summary className="cursor-pointer select-none font-medium">
          Options
          <span className="ml-2 font-normal text-muted-foreground">
            {preset.title}
            {catalogReady && missing.length === 0 && (
              <>
                {needsPresenter && (
                  <>
                    {" · "}
                    {avatarLabel(catalogReady.avatars.find((a) => a.avatar_id === avatarId) ?? catalogReady.avatars[0])}
                  </>
                )}
                {" · "}
                {voiceLabel(catalogReady.voices.find((v) => voiceIdOf(v) === voiceId) ?? catalogReady.voices[0])}
              </>
            )}
          </span>
        </summary>
        <fieldset className="mt-3">
          <legend className="mb-2 text-sm font-medium">Classic formats</legend>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {CLASSIC_PRESETS.map((option) => {
              const selected = option.id === preset.id;
              const lock = presetLock(option.id, isLink, availability);
              return (
                <label
                  key={option.id}
                  className={cn(
                    "flex flex-col gap-1 rounded-lg border p-3 transition-colors",
                    lock ? "cursor-not-allowed opacity-60" : "cursor-pointer",
                    selected
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/50",
                  )}
                >
                  <input
                    type="radio"
                    name="preset"
                    value={option.id}
                    checked={selected}
                    onChange={() => {
                      setPresetId(option.id);
                      setPresetTouched(true);
                    }}
                    className="sr-only"
                    disabled={busy || lock !== null}
                  />
                  <span className="text-sm font-medium">{option.title}</span>
                  <span className="text-xs text-muted-foreground">{option.blurb}</span>
                  {lock && (
                    <span className="text-xs font-medium text-muted-foreground">
                      {lockedOptionReason(lock)}
                    </span>
                  )}
                </label>
              );
            })}
          </div>
        </fieldset>
        {catalogReady && missing.length === 0 && (
          <div className={cn("mt-3 grid gap-3", needsPresenter ? "sm:grid-cols-3" : "sm:grid-cols-2")}>
            {needsPresenter && (
              <SelectField
                id="one-flow-avatar"
                label="Presenter"
                value={avatarId}
                onChange={(value) => {
                  setAvatarId(value);
                  const avatar = catalogReady.avatars.find((a) => a.avatar_id === value);
                  const paired = defaultVoiceFor(avatar, catalogReady.voices);
                  if (avatar?.voice_name && paired) setVoiceId(paired);
                }}
                options={catalogReady.avatars.map((a) => ({ value: a.avatar_id, label: avatarLabel(a) }))}
                disabled={busy}
              />
            )}
            <SelectField
              id="one-flow-voice"
              label="Voice"
              value={voiceId}
              onChange={setVoiceId}
              options={catalogReady.voices.map((v) => ({ value: voiceIdOf(v), label: voiceLabel(v) }))}
              disabled={busy}
            />
            <SelectField
              id="one-flow-language"
              label="Language"
              value={language}
              onChange={(value) => setLanguage(coerceLanguage(value, "auto"))}
              options={LANGUAGE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              disabled={busy}
            />
          </div>
        )}
      </details>

      <div className="flex flex-col gap-3 border-t border-border pt-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Coins className="size-4 shrink-0" aria-hidden />
          <span>
            {firstReel ? "1 free reel" : `${runSize} credits`}
            {credits !== null && ` · you have ${credits}`}
          </span>
        </p>
        <Button type="submit" size="lg" disabled={!canSubmit}>
          {busy ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden />
              {phase === "reading"
                ? "Reading the page…"
                : firstReel
                  ? "Starting your reel…"
                  : `Starting ${runSize} renders…`}
            </>
          ) : (
            <>
              {firstReel ? "Make my free reel" : `Make ${runSize} reels`}{" "}
              <ArrowRight className="size-4" aria-hidden />
            </>
          )}
        </Button>
      </div>

      {selectedLock && (
        <p role="status" className="flex items-start gap-2 text-sm text-muted-foreground">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {`${preset.title}: ${selectedLock.label}. ${lockedOptionReason(selectedLock)}`}
            {!isLink && selectedLock.id === "generated_script" &&
              " Paste a product or page link instead, and the scripts are written from the page."}
          </span>
        </p>
      )}

      {(notEnoughCredits || outOfCredits) && (
        <Card>
          <CardContent className="space-y-3 p-4">
            <p className="text-sm font-medium">
              {runSize === 1 ? "A reel needs 1 credit" : `${runSize} reels need ${runSize} credits`}
              {credits !== null ? ` and you have ${credits}` : ""}. Top up in one click:
            </p>
            <PlanUpsell reason="out_of_credits" />
            <BuyCredits />
            <p className="text-xs text-muted-foreground">
              Or{" "}
              <Link href="/referral" className="underline underline-offset-4">
                invite a friend for free credits
              </Link>
              .
            </p>
          </CardContent>
        </Card>
      )}

      {error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{error}</span>
        </p>
      )}
    </form>
  );
}

/**
 * Link-run scripts. A style asks the API for one hook per format of its hook
 * family (meme captions, POV, before/after ...) written from the page; if that
 * call fails the run still starts with the classic hook angles.
 */
async function planLinkRun(
  preset: CreatePreset,
  content: PageContent,
  language: Language,
  token: string | null | undefined,
): Promise<LinkVariantPlan[]> {
  if (preset.style) {
    try {
      const written = await writeStyleHooks(
        {
          style: preset.style,
          title: content.title,
          description: content.description,
          features: content.features,
          language,
        },
        { token: token ?? undefined },
      );
      const plans = planStyleVariants(content, language, written.hooks ?? []);
      if (plans.length > 0) return plans;
    } catch {
      // Fall through to the classic angles: the reels still render.
    }
  }
  return planLinkVariants(content, language);
}

interface StylePickerProps {
  readonly presets: readonly CreatePreset[];
  readonly selectedId: PresetId;
  readonly disabled: boolean;
  readonly lockOf: (id: PresetId) => LockedFormat | null;
  readonly onPick: (id: PresetId) => void;
}

/** One-click style chips, right under the box: pick one, press make. */
function StylePicker({ presets, selectedId, disabled, lockOf, onPick }: StylePickerProps) {
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium">Style</legend>
      <div className="flex flex-wrap gap-2">
        {presets.map((option) => {
          const selected = option.id === selectedId;
          const lock = lockOf(option.id);
          return (
            <label
              key={option.id}
              title={lock ? lockedOptionReason(lock) : option.blurb}
              className={cn(
                "rounded-full border px-3 py-1.5 text-sm transition-colors",
                lock ? "cursor-not-allowed opacity-50" : "cursor-pointer",
                selected
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:border-primary/50 hover:text-foreground",
              )}
            >
              <input
                type="radio"
                name="style"
                value={option.id}
                checked={selected}
                onChange={() => onPick(option.id)}
                className="sr-only"
                disabled={disabled || lock !== null}
              />
              {option.title}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/** Fires `onFire` once after mount (used to auto-start a prefilled run). */
function AutoSubmit({ onFire }: Readonly<{ onFire: () => void }>) {
  const fire = React.useRef(onFire);
  React.useEffect(() => {
    fire.current();
  }, []);
  return null;
}

function LoadingRow({ label }: Readonly<{ label: string }>) {
  return (
    <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

interface SelectFieldProps {
  readonly id: string;
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly options: readonly { value: string; label: string }[];
  readonly disabled?: boolean;
}

function SelectField({ id, label, value, onChange, options, disabled }: SelectFieldProps) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs text-muted-foreground">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
