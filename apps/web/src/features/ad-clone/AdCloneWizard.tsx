"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import { ApiError } from "@/src/shared/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

import {
  RENDER_DONE,
  RENDER_FAILED,
  approveRender,
  classifyAdCloneFailure,
  getRender,
  listProducts,
  makeBrief,
  makeClone,
  type AdCloneAspect,
  type AdCloneBrief,
  type AdCloneLanguage,
  type AdCloneProduct,
  type AdCloneRenderJob,
  type AdCloneResult,
  type AdCloneSettings,
} from "./api";
import { BriefPanel } from "./BriefPanel";
import { DEFAULT_SETTINGS, LANGUAGES, linkProblem } from "./model";
import { RenderStatus } from "./RenderStatus";
import { VariationCard } from "./ResultView";

const POLL_MS = 5000;
/** Set by the competitor tracker's "Clone this" (`/ad-clone?from=tracked`). */
export const TRACKED_BRIEF_KEY = "menivor.adclone.trackedBrief";

/** The brief the competitor tracker handed over, read once and cleared. */
export function takeTrackedBrief(): AdCloneBrief | null {
  if (typeof window === "undefined") return null;
  if (new URLSearchParams(window.location.search).get("from") !== "tracked") return null;
  try {
    const raw = window.sessionStorage.getItem(TRACKED_BRIEF_KEY);
    window.sessionStorage.removeItem(TRACKED_BRIEF_KEY);
    const parsed = raw ? (JSON.parse(raw) as { brief?: AdCloneBrief }) : null;
    return parsed?.brief ?? null;
  } catch {
    return null;
  }
}

function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const STEPS = ["ad", "product", "clone"] as const;
type Step = (typeof STEPS)[number];
const TITLES: Record<Step, string> = { ad: "Winning ad", product: "Your product", clone: "Clone" };

function Choice<T extends string | number>({
  label,
  value,
  options,
  onPick,
}: Readonly<{ label: string; value: T; options: readonly { value: T; label: string }[]; onPick: (v: T) => void }>) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <button
            key={String(o.value)}
            type="button"
            aria-pressed={value === o.value}
            onClick={() => onPick(o.value)}
            className={cn(
              "glass-subtle rounded-xl px-4 py-2 text-sm transition-colors hover:border-primary/60",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              value === o.value && "border-primary/70 font-medium",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

/** Winning ad -> your product -> clone. One action per step; prices are shown before anything renders. */
export function AdCloneWizard() {
  const getApiToken = useApiToken();
  const [step, setStep] = React.useState<Step>("ad");
  const [url, setUrl] = React.useState("");
  const [touched, setTouched] = React.useState(false);
  const [brief, setBrief] = React.useState<AdCloneBrief | null>(null);
  const [products, setProducts] = React.useState<readonly AdCloneProduct[]>([]);
  const [settings, setSettings] = React.useState<AdCloneSettings>(DEFAULT_SETTINGS);
  const [result, setResult] = React.useState<AdCloneResult | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState("");
  const [guard, setGuard] = React.useState<readonly string[]>([]);
  const [render, setRender] = React.useState<AdCloneRenderJob | null>(null);
  const [approvalKey, setApprovalKey] = React.useState("");
  const [fromTracker, setFromTracker] = React.useState(false);

  React.useEffect(() => {
    const handed = takeTrackedBrief();
    if (!handed) return;
    setBrief(handed);
    setFromTracker(true);
    setStep("product");
    void (async () => {
      try {
        setProducts((await listProducts({ token: await getApiToken() })).products);
      } catch (err) {
        setProblem(friendlyErrorMessage(err, "We could not load your products. Try again."));
      }
    })();
  }, [getApiToken]);

  React.useEffect(() => {
    if (!render || render.state === RENDER_DONE || render.state === RENDER_FAILED) return undefined;
    const timer = setTimeout(async () => {
      try {
        setRender(await getRender(render.job_id, { token: await getApiToken() }));
      } catch (err) {
        setProblem(friendlyErrorMessage(err, "We lost track of this render; it will still appear in My reels."));
      }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [getApiToken, render]);

  const product = products.find((p) => p.id === settings.product) ?? null;
  const urlProblem = linkProblem(url);

  const fail = React.useCallback((err: unknown, fallback: string) => {
    const kind = classifyAdCloneFailure(err);
    if (kind.kind === "ip_guard") {
      setGuard(kind.problems);
      setProblem("This clone was stopped because it would reuse something from the original ad.");
    } else if (kind.kind === "off") {
      setProblem("This is not switched on for your account yet.");
    } else if (kind.kind === "credits") {
      setProblem("You need more AI-video credits for this render.");
    } else if (kind.kind === "link") {
      setProblem(kind.message || fallback);
    } else {
      setProblem(friendlyErrorMessage(err, fallback));
    }
  }, []);

  const analyse = async () => {
    setTouched(true);
    if (urlProblem) return;
    setBusy(true);
    setProblem("");
    try {
      const token = await getApiToken();
      const [made, list] = await Promise.all([makeBrief(url.trim(), { token }), listProducts({ token })]);
      setBrief(made.brief);
      setProducts(list.products);
      setStep("product");
    } catch (err) {
      fail(err, "We could not read that ad. Check the link and try again.");
    } finally {
      setBusy(false);
    }
  };

  const clone = async () => {
    if (!brief) return;
    setBusy(true);
    setProblem("");
    setGuard([]);
    try {
      setResult(await makeClone(brief, settings, { token: await getApiToken() }));
    } catch (err) {
      fail(err, "We could not write the clone. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    const first = result?.variations[0];
    if (!first) return;
    const key = approvalKey || newKey();
    setApprovalKey(key); // a retried click reuses the key, so the server replays instead of charging twice
    setBusy(true);
    setProblem("");
    try {
      const token = await getApiToken();
      const started = await approveRender(first.plan, first.engine.engine, first.ai_video_credits, key, { token });
      setRender(await getRender(started.job_id, { token }));
    } catch (err) {
      if (err instanceof ApiError && err.status >= 500) {
        setProblem("The render did not start. Nothing was charged; try again.");
      } else {
        fail(err, "The render did not start. Nothing was charged.");
      }
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <Card>
        <CardContent className="space-y-5 p-6">
          <h2 className="text-xl font-semibold">Your clones</h2>
          <p className="text-sm text-muted-foreground">
            Voice: {result.voice.label}. Each version ends on &quot;{result.product.cta}&quot;.
          </p>
          {result.variations.map((v, i) => (
            <VariationCard key={v.plan.slug} variation={v} index={i} />
          ))}
          {render ? <RenderStatus job={render} /> : null}
          {!result.paid_render ? (
            <p className="text-sm text-muted-foreground">Paid rendering is switched off on this server.</p>
          ) : null}
          {problem ? <p role="alert" className="text-sm text-destructive">{problem}</p> : null}
          <div className="flex items-center justify-between gap-3">
            <Button variant="ghost" onClick={() => setResult(null)} disabled={busy || render !== null}>
              Back
            </Button>
            {render ? null : (
              <Button onClick={() => void approve()} disabled={busy || !result.paid_render}>
                {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}
                Approve and render ({result.variations[0]?.ai_video_credits ?? 0} credits)
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    );
  }

  const index = STEPS.indexOf(step);
  const pick = (patch: Partial<AdCloneSettings>) => setSettings((prev) => ({ ...prev, ...patch }));

  return (
    <Card>
      <CardContent className="space-y-6 p-6">
        <div>
          <p className="text-xs text-muted-foreground">
            Step {index + 1} of {STEPS.length}
          </p>
          <h2 className="text-xl font-semibold">{TITLES[step]}</h2>
          {fromTracker && step !== "ad" ? (
            <p className="mt-1 text-sm text-muted-foreground">From your competitor tracker</p>
          ) : null}
        </div>

        {step === "ad" ? (
          <div className="space-y-2">
            <Label htmlFor="ac-url">Link to the winning ad</Label>
            <Input
              id="ac-url"
              inputMode="url"
              placeholder="https://vt.tiktok.com/..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              aria-invalid={touched && urlProblem !== ""}
            />
            {touched && urlProblem ? <p className="text-sm text-destructive">{urlProblem}</p> : null}
            <p className="text-sm text-muted-foreground">We read its hook, shots and pacing. Its footage is deleted right after.</p>
          </div>
        ) : null}

        {step === "product" ? (
          <ul className="grid gap-3" aria-label="Products">
            {products.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  aria-pressed={settings.product === p.id}
                  onClick={() => pick({ product: p.id })}
                  className={cn(
                    "glass-subtle w-full rounded-2xl p-5 text-left transition-colors hover:border-primary/60",
                    settings.product === p.id && "border-primary/70",
                  )}
                >
                  <span className="block font-semibold">{p.product}</span>
                  <span className="block text-sm text-muted-foreground">
                    {p.brand_name}. Cast: {p.characters.map((c) => c.name).join(", ")}. Ends on {p.end_card}.
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        {step === "clone" && brief ? (
          <div className="space-y-5">
            <Choice<AdCloneAspect>
              label="Aspect"
              value={settings.aspect}
              options={[{ value: "9:16", label: "9:16 vertical" }, { value: "16:9", label: "16:9 wide" }]}
              onPick={(aspect) => pick({ aspect })}
            />
            <Choice<1 | 2 | 3>
              label="Variations"
              value={settings.variations}
              options={[{ value: 1, label: "1" }, { value: 2, label: "2" }, { value: 3, label: "3" }]}
              onPick={(variations) => pick({ variations })}
            />
            <Choice<AdCloneLanguage>
              label="Language"
              value={settings.language}
              options={LANGUAGES}
              onPick={(language) => pick({ language })}
            />
            <BriefPanel brief={brief} productName={product?.product ?? "your product"} count={settings.variations} />
          </div>
        ) : null}

        {problem ? <p role="alert" className="text-sm text-destructive">{problem}</p> : null}
        {guard.length ? (
          <ul className="list-disc pl-5 text-xs text-destructive" aria-label="What was blocked">
            {guard.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        ) : null}

        <div className="flex min-h-10 items-center justify-between gap-3">
          {index > 0 ? (
            <Button variant="ghost" onClick={() => setStep(STEPS[index - 1] ?? "ad")} disabled={busy}>
              Back
            </Button>
          ) : (
            <span />
          )}
          {step === "ad" ? (
            <Button onClick={() => void analyse()} disabled={busy}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Read the ad
            </Button>
          ) : null}
          {step === "product" ? (
            <Button onClick={() => setStep("clone")} disabled={!product}>
              Continue
            </Button>
          ) : null}
          {step === "clone" ? (
            <Button onClick={() => void clone()} disabled={busy}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Clone
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
