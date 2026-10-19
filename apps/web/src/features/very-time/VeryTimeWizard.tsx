"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { signInHref } from "@/lib/auth-redirect";
import { useSignedInState } from "@/lib/auth-state";
import { useApiToken } from "@/lib/use-api-token";
import { STORY_DONE, STORY_FAILED } from "@/src/features/story8/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

import {
  classifyFailure,
  getVeryTimeJob,
  makeTakes,
  planVeryTime,
  startVeryTime,
  type VeryTimeBrand,
  type VeryTimeBrandPreset,
  type VeryTimeDuration,
  type VeryTimeJob,
  type VeryTimeLook,
  type VeryTimeMode,
  type VeryTimePlan,
  type VeryTimeTakes,
} from "./api";
import {
  DEFAULT_DURATION,
  DEFAULT_GARMENT,
  DEFAULT_SOUND,
  DEFAULT_VOICE,
  EMPTY_FORM,
  buildInput,
  changeVoice,
  cleanPlace,
  defaultChestText,
  placeReady,
  previewLine,
  takesCount,
  type SoundChoice,
  type VeryTimeForm,
  type VoiceChoice,
} from "./model";
import { ResultView } from "./ResultView";
import { BrandStep } from "./steps/BrandStep";
import { LengthStep } from "./steps/LengthStep";
import { LookStep } from "./steps/LookStep";
import { PlaceStep } from "./steps/PlaceStep";
import { PriceStep } from "./steps/PriceStep";
import { SoundStep } from "./steps/SoundStep";
import { VoiceStep } from "./steps/VoiceStep";

const POLL_MS = 4000;
const TOP_UP_HREF = "/wallet/plans";

const STEPS = ["place", "look", "length", "brand", "voice", "sound", "price"] as const;
type Step = (typeof STEPS)[number];
const TITLES: Record<Step, string> = {
  place: "Your place",
  look: "Look",
  length: "Length",
  brand: "Your brand",
  voice: "Voice",
  sound: "Sound",
  price: "Price and make",
};
const VOICE_UNAVAILABLE = "Premium voice is not available right now; the free voice still works.";

type Failure = { readonly text: string; readonly topUp: boolean } | null;

/** Place, look, length, brand (optional), voice, sound, price, then the finished video. One action per step. */
export function VeryTimeWizard() {
  const { isLoaded, isSignedIn } = useSignedInState();
  const getApiToken = useApiToken();
  const [step, setStep] = React.useState<Step>("place");
  const [form, setForm] = React.useState<VeryTimeForm>(EMPTY_FORM);
  const [brandDraft, setBrandDraft] = React.useState<VeryTimeBrand>({});
  const [brandEdited, setBrandEdited] = React.useState(false);
  const [brandPreset, setBrandPreset] = React.useState<VeryTimeBrandPreset | null>(null);
  const [lineDraft, setLineDraft] = React.useState("");
  const [lineEdited, setLineEdited] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const [voice, setVoice] = React.useState<VoiceChoice>(DEFAULT_VOICE);
  const [sound, setSound] = React.useState<SoundChoice>(DEFAULT_SOUND);
  const [takes, setTakes] = React.useState<VeryTimeTakes | null>(null);
  const [makingTakes, setMakingTakes] = React.useState(false);
  const [takesProblem, setTakesProblem] = React.useState("");
  const [blocked, setBlocked] = React.useState<readonly string[]>([]);
  const [plan, setPlan] = React.useState<VeryTimePlan | null>(null);
  const [mode, setMode] = React.useState<VeryTimeMode>("frames");
  const [job, setJob] = React.useState<VeryTimeJob | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  const [failure, setFailure] = React.useState<Failure>(null);

  React.useEffect(() => {
    if (!job || job.state === STORY_DONE || job.state === STORY_FAILED) return undefined;
    const timer = setTimeout(async () => {
      try {
        setJob(await getVeryTimeJob(job.job_id, { token: await getApiToken() }));
      } catch (err) {
        setFailure({ text: friendlyErrorMessage(err, "We lost track of this video; open your reels to find it."), topUp: false });
      }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [getApiToken, job]);

  const handleFailure = React.useCallback((err: unknown, fallback: string): "quote_changed" | null => {
    const kind = classifyFailure(err);
    if (kind.kind === "guard") {
      setBlocked(kind.terms);
      setPlan(null);
      setStep("place");
      return null;
    }
    if (kind.kind === "quote_changed") return "quote_changed";
    if (kind.kind === "credits") {
      const what = kind.aiVideo ? "AI-video credits" : "credits";
      setFailure({ text: `You need more ${what} for this version.`, topUp: true });
      return null;
    }
    setFailure({ text: friendlyErrorMessage(err, fallback), topUp: false });
    return null;
  }, []);

  const runPlan = React.useCallback(
    async (current: VeryTimeForm) => {
      setPlan(null);
      setFailure(null);
      try {
        setPlan(await planVeryTime(buildInput(current), { token: await getApiToken() }));
        setBlocked([]);
      } catch (err) {
        handleFailure(err, "We could not price this video.");
      }
    },
    [getApiToken, handleFailure],
  );

  if (isLoaded && !isSignedIn) {
    return (
      <p className="text-sm">
        <Link className="underline" href={signInHref("/very-time")}>Sign in</Link> to make a video.
      </p>
    );
  }

  const patch = (change: Partial<VeryTimeForm>) => setForm((prev) => ({ ...prev, ...change }));

  const shownBrand: VeryTimeBrand =
    brandPreset === "oxhan" ? { preset: "oxhan" } : { ...brandDraft, ...(brandPreset ? { preset: brandPreset } : {}) };

  const goVoice = (brand: VeryTimeBrand | null) => {
    patch({ brand, line: brand && brand.preset !== "oxhan" ? lineDraft : undefined });
    setStep("voice");
  };

  const pickLength = (duration: VeryTimeDuration) => {
    patch({ duration });
    setStep("brand");
  };

  const goPrice = () => {
    const next = { ...form, voice, sound };
    setForm(next);
    setStep("price");
    void runPlan(next);
  };

  const updateVoice = (change: Partial<Omit<VoiceChoice, "takeKey">>) => {
    const next = changeVoice(voice, change);
    if (next.takeKey === null) setTakes(null);
    setVoice(next);
    setTakesProblem("");
  };

  const runTakes = async () => {
    setMakingTakes(true);
    setTakesProblem("");
    const asked = voice;
    try {
      const reply = asked.reply.trim();
      const result = await makeTakes(
        {
          place_word: cleanPlace(form.place),
          engine: asked.engine,
          delivery: asked.delivery,
          count: takesCount(asked.engine),
          ...(reply ? { reply_line: reply } : {}),
        },
        { token: await getApiToken() },
      );
      setTakes(result);
      setVoice((prev) => ({ ...prev, takeKey: result.recommended || result.takes[0]?.key || null }));
    } catch (err) {
      const kind = classifyFailure(err);
      if (kind.kind === "guard") {
        setBlocked(kind.terms);
        setStep("place");
      } else if (kind.kind === "voice_unavailable") {
        setTakesProblem(VOICE_UNAVAILABLE);
      } else if (kind.kind === "rate_limited") {
        setTakesProblem("You made a lot of takes just now. Wait a few minutes, or continue and we pick one for you.");
      } else {
        setTakesProblem(friendlyErrorMessage(err, "We could not make takes. Continue and we pick one for you."));
      }
    } finally {
      setMakingTakes(false);
    }
  };

  const pickLook = (look: VeryTimeLook) => {
    patch({ look });
    if (!brandEdited) {
      setBrandDraft({ garment: DEFAULT_GARMENT, chest_text: defaultChestText(form.place) });
    }
    if (!lineEdited) setLineDraft(previewLine(form.place));
    setStep("length");
  };

  const make = async () => {
    if (!plan) return;
    setBusy(true);
    setFailure(null);
    setNotice("");
    try {
      const token = await getApiToken();
      const started = await startVeryTime({ ...buildInput(form), mode, quoted: plan.quote[mode] }, { token });
      setJob(await getVeryTimeJob(started.job_id, { token }));
    } catch (err) {
      if (handleFailure(err, "We could not start this video.") === "quote_changed") {
        await runPlan(form);
        setNotice("The price changed a moment ago. Here is the new price; nothing was charged.");
      }
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setJob(null);
    setPlan(null);
    setNotice("");
    setFailure(null);
    setStep("place");
  };

  if (job) {
    return (
      <Card>
        <CardContent className="p-6">
          <ResultView job={job} onAnother={reset} endCta={plan?.end_card?.cta ?? ""} />
          {failure ? <p role="alert" className="mt-3 text-sm text-destructive">{failure.text}</p> : null}
        </CardContent>
      </Card>
    );
  }

  const index = STEPS.indexOf(step);
  const back = () => {
    setFailure(null);
    setNotice("");
    setStep(STEPS[Math.max(0, index - 1)] ?? "place");
  };

  return (
    <Card>
      <CardContent className="space-y-6 p-6">
        <div>
          <p className="text-xs text-muted-foreground">
            Step {index + 1} of {STEPS.length}
          </p>
          <h2 className="text-xl font-semibold">{TITLES[step]}</h2>
          {step === "brand" ? (
            <p className="mt-1 text-sm text-muted-foreground">Optional. Use Oxhan Atelier or put your own brand in the video.</p>
          ) : null}
        </div>

        {step === "place" ? <PlaceStep form={form} blocked={blocked} onChange={patch} /> : null}
        {step === "look" ? <LookStep value={form.look} onPick={pickLook} /> : null}
        {step === "length" ? <LengthStep value={form.duration ?? DEFAULT_DURATION} onPick={pickLength} /> : null}
        {step === "brand" ? <BrandStep
            brand={shownBrand}
            line={lineDraft}
            onUploading={setUploading}
            onLine={(line) => {
              setLineEdited(true);
              setLineDraft(line);
            }}
            onChange={(brand) => {
              if (brand.preset === "oxhan") {
                setBrandPreset("oxhan");
                return;
              }
              setBrandPreset("custom");
              const { preset: _preset, ...fields } = brand;
              if (brandPreset === "custom") setBrandEdited(true);
              setBrandDraft(fields);
            }}
          /> : null}
        {step === "voice" ? (
          <VoiceStep
            voice={voice}
            takes={takes}
            makingTakes={makingTakes}
            takesProblem={takesProblem}
            onChange={updateVoice}
            onPickTake={(key) => setVoice((prev) => ({ ...prev, takeKey: key }))}
            onMakeTakes={() => void runTakes()}
          />
        ) : null}
        {step === "sound" ? <SoundStep sound={sound} onChange={setSound} /> : null}
        {step === "price" ? <PriceStep plan={plan} mode={mode} onMode={setMode} /> : null}

        {notice ? <p role="status" className="text-sm">{notice}</p> : null}
        {failure ? (
          <p role="alert" className="text-sm text-destructive">
            {failure.text}{" "}
            {failure.topUp ? (
              <Link href={TOP_UP_HREF} className="underline underline-offset-4">
                Add credits
              </Link>
            ) : null}
          </p>
        ) : null}

        <div className="flex min-h-10 items-center justify-between gap-3">
          {index > 0 ? (
            <Button variant="ghost" onClick={back} disabled={busy}>
              Back
            </Button>
          ) : (
            <span />
          )}
          {step === "place" ? (
            <Button onClick={() => setStep("look")} disabled={!placeReady(form)}>
              Continue
            </Button>
          ) : null}
          {step === "brand" ? (
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => goVoice(null)} disabled={uploading}>
                Skip
              </Button>
              <Button onClick={() => goVoice(shownBrand)} disabled={uploading || brandPreset === null}>
                Continue
              </Button>
            </div>
          ) : null}
          {step === "voice" ? (
            <Button onClick={() => setStep("sound")} disabled={makingTakes}>
              Continue
            </Button>
          ) : null}
          {step === "sound" ? <Button onClick={goPrice}>Continue</Button> : null}
          {step === "price" ? (
            <Button onClick={() => void make()} disabled={busy || !plan}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Make it
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
