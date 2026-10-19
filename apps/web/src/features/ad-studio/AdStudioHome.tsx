"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Link2, Loader2, PenLine, Save, Sparkles, Target } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ApiError } from "@/src/shared/api";
import { AnglesEditor } from "./AnglesEditor";
import { analyzeProduct, createAdProject, productToInput, type AdLanguage, type AnalyzeInput, type AnalyzeResult } from "./api";
import { EMPTY_MANUAL, ManualProductForm, manualToInput, type ManualDraft } from "./ManualProductForm";
import { ProductCard } from "./ProductCard";
import { EMPTY_PREFILL, hasPrefill, prefillDescription, type AdStudioPrefill } from "./prefill";
import { ProjectList } from "./ProjectList";
import { ErrorText, errorMessage, useRequestOptions } from "./shared";

type Mode = "url" | "manual";

/** Paste a product URL (or enter it manually) -> review angles -> save a project. */
export function AdStudioHome({ prefill = EMPTY_PREFILL }: { prefill?: AdStudioPrefill }) {
  const router = useRouter();
  const requestOptions = useRequestOptions();
  const [mode, setMode] = React.useState<Mode>(!prefill.url && prefill.offer ? "manual" : "url");
  const [url, setUrl] = React.useState(prefill.url);
  const [manual, setManual] = React.useState<ManualDraft>(() => ({
    ...EMPTY_MANUAL,
    description: prefillDescription(prefill),
  }));
  const [language, setLanguage] = React.useState<"" | AdLanguage>("");
  const [useLlm, setUseLlm] = React.useState(true);
  const [analysis, setAnalysis] = React.useState<AnalyzeResult | null>(null);
  const [busy, setBusy] = React.useState<"" | "analyze" | "save">("");
  const [error, setError] = React.useState("");

  const input = (): AnalyzeInput => ({
    ...(mode === "url" ? { url: url.trim() } : { product: manualToInput(manual) }),
    ...(language ? { language } : {}),
    use_llm: useLlm,
    angle_count: 5,
  });

  const analyze = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (mode === "url" && !/^https?:\/\//i.test(url.trim())) {
      setError("Paste a full product link starting with https://");
      return;
    }
    if (mode === "manual" && !manual.title.trim()) {
      setError("Enter the product name.");
      return;
    }
    setBusy("analyze");
    try {
      setAnalysis(await analyzeProduct(input(), await requestOptions()));
    } catch (err) {
      setAnalysis(null);
      setError(errorMessage(err));
      // Stores that block bots (HTTP 424) can still be used with manual details.
      if (err instanceof ApiError && err.status === 424 && mode === "url") setMode("manual");
    } finally {
      setBusy("");
    }
  };

  const save = async () => {
    if (!analysis) return;
    setBusy("save");
    setError("");
    try {
      const project = await createAdProject(
        {
          url: analysis.product.url || undefined,
          product: productToInput(analysis.product),
          use_llm: useLlm,
          language: analysis.language,
          angles: analysis.angles.map(({ kind, hook, pain, proof, offer, cta, source }) => ({
            kind, hook, pain, proof, offer, cta, source,
          })),
        },
        await requestOptions(),
      );
      router.push(`/ad-studio/${project.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy("");
    }
  };

  const applyOffer = () => {
    if (!analysis || !prefill.offer) return;
    setAnalysis({
      ...analysis,
      angles: analysis.angles.map((a) => ({ ...a, offer: prefill.offer, source: "edited" })),
    });
  };

  return (
    <div className="space-y-8">
      {hasPrefill(prefill) ? <PrefillNotice prefill={prefill} /> : null}
      <Card>
        <CardContent className="p-5">
          <form onSubmit={analyze} className="space-y-4">
            <div className="flex flex-wrap gap-2" role="tablist" aria-label="Product source">
              <Button type="button" size="sm" variant={mode === "url" ? "default" : "outline"} onClick={() => setMode("url")}>
                <Link2 aria-hidden /> Product link
              </Button>
              <Button type="button" size="sm" variant={mode === "manual" ? "default" : "outline"} onClick={() => setMode("manual")}>
                <PenLine aria-hidden /> Enter manually
              </Button>
            </div>
            {mode === "url" ? (
              <div className="grid gap-1">
                <Label htmlFor="ad-url">Product URL</Label>
                <Input
                  id="ad-url"
                  type="url"
                  inputMode="url"
                  placeholder="https://yourstore.com/product"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  disabled={busy !== ""}
                />
                <p className="text-xs text-muted-foreground">
                  Works with most online stores. If a store blocks us, enter the details manually.
                </p>
              </div>
            ) : (
              <ManualProductForm draft={manual} onChange={setManual} disabled={busy !== ""} />
            )}
            <div className="flex flex-wrap items-end gap-4">
              <div className="grid gap-1">
                <Label htmlFor="ad-lang">Ad language</Label>
                <Select id="ad-lang" value={language} onChange={(e) => setLanguage(e.target.value as "" | AdLanguage)} disabled={busy !== ""}>
                  <option value="">Match the store</option>
                  <option value="tr">Turkish</option>
                  <option value="en">English</option>
                </Select>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} disabled={busy !== ""} />
                Write copy with AI
              </label>
              <Button type="submit" disabled={busy !== ""}>
                {busy === "analyze" ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
                {busy === "analyze" ? "Reading product..." : "Draft ad angles"}
              </Button>
            </div>
            <ErrorText message={error} />
          </form>
        </CardContent>
      </Card>

      {analysis ? (
        <section className="space-y-4" aria-labelledby="angles-heading">
          <ProductCard product={analysis.product} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 id="angles-heading" className="text-lg font-semibold">Ad angles</h2>
              <p className="text-sm text-muted-foreground">
                Copy uses only facts found on the product page. Edit anything before saving.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {prefill.offer ? (
                <Button variant="outline" onClick={applyOffer} disabled={busy !== ""}>
                  <Target aria-hidden /> Use my offer in every angle
                </Button>
              ) : null}
              <Button onClick={save} disabled={busy !== ""}>
              {busy === "save" ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
              {busy === "save" ? "Saving and importing images..." : "Save project"}
              </Button>
            </div>
          </div>
          <AnglesEditor
            angles={analysis.angles}
            onChange={(angles) => setAnalysis({ ...analysis, angles })}
            disabled={busy !== ""}
          />
        </section>
      ) : null}

      <ProjectList />
    </div>
  );
}

/** Shows what a deep link carried in, so nothing arrives silently. */
function PrefillNotice({ prefill }: { prefill: AdStudioPrefill }) {
  return (
    <div className="rounded-md border border-primary/40 bg-primary/5 p-4 text-sm" role="status">
      <p className="font-medium">
        {prefill.source === "rally" ? "Brought over from your Rally campaign" : "Filled in from your link"}
      </p>
      <dl className="mt-2 grid gap-1 text-muted-foreground">
        {prefill.url ? (
          <div className="flex flex-wrap gap-1">
            <dt className="font-medium text-foreground">Site:</dt>
            <dd className="break-all">{prefill.url}</dd>
          </div>
        ) : null}
        {prefill.offer ? (
          <div className="flex flex-wrap gap-1">
            <dt className="font-medium text-foreground">Offer:</dt>
            <dd>{prefill.offer}</dd>
          </div>
        ) : null}
        {prefill.audience ? (
          <div className="flex flex-wrap gap-1">
            <dt className="font-medium text-foreground">Audience:</dt>
            <dd>{prefill.audience}</dd>
          </div>
        ) : null}
      </dl>
      <p className="mt-2 text-xs text-muted-foreground">
        Review the details below, then draft your ad angles. Nothing runs until you press the button.
      </p>
    </div>
  );
}
