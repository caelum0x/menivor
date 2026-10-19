"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Copy as CopyIcon, FilePlus2, LayoutTemplate, Loader2, Sparkles, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

import {
  createDesign,
  deleteDesign,
  duplicateDesign,
  generateDesigns,
  listBrandKits,
  listDesigns,
  listTemplates,
} from "./api";
import { requestFonts, fontsIn } from "./fonts";
import { PageView, imageKeys, useImageUrls } from "./PageView";
import { ErrorText, blankCanvas, errorMessage, fitScale, formatDate, useRequestOptions } from "./shared";
import {
  SIZE_LABELS,
  type BrandKitInfo,
  type DesignSummary,
  type GenerateResult,
  type SizePreset,
  type TemplateInfo,
} from "./types";

const STATUS_LABEL: Record<string, string> = { draft: "Draft", exported: "Exported", scheduled: "Scheduled" };

function OptionCard({
  option,
  result,
  busy,
  onUse,
  getOptions,
}: {
  option: GenerateResult["options"][number];
  result: GenerateResult;
  busy: boolean;
  onUse: () => void;
  getOptions: () => Promise<{ token?: string }>;
}) {
  const page = option.canvas.pages[0];
  const urls = useImageUrls(imageKeys(option.canvas.pages), getOptions);
  const scale = fitScale(result.width, result.height, 260, 300);
  return (
    <Card className="overflow-hidden">
      <div className="flex justify-center bg-secondary/40 p-3">
        {page ? <PageView page={page} width={result.width} height={result.height} scale={scale} imageUrls={urls} /> : null}
      </div>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="font-medium">{option.name}</p>
          {option.canvas.pages.length > 1 ? <Badge variant="secondary">{option.canvas.pages.length} slides</Badge> : null}
        </div>
        <p className="text-xs text-muted-foreground">{option.description}</p>
        <Button className="w-full" onClick={onUse} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}
          Edit this layout
        </Button>
      </CardContent>
    </Card>
  );
}

function DesignCard({
  design,
  onDuplicate,
  onDelete,
}: {
  design: DesignSummary;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  return (
    <Card className="overflow-hidden">
      <Link href={`/studio/design/${design.id}`} className="block bg-secondary/40">
        <div className="flex h-40 items-center justify-center">
          {design.thumb_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={design.thumb_url} alt="" className="max-h-40 max-w-full object-contain" />
          ) : (
            <span className="text-xs text-muted-foreground">Not exported yet</span>
          )}
        </div>
      </Link>
      <CardContent className="space-y-2 p-3">
        <Link href={`/studio/design/${design.id}`} className="block truncate font-medium hover:underline">
          {design.title}
        </Link>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant={design.status === "scheduled" ? "success" : "outline"}>{STATUS_LABEL[design.status] ?? design.status}</Badge>
          <span>{SIZE_LABELS[design.size_preset] ?? design.size_preset}</span>
          <span>{formatDate(design.updated_at)}</span>
        </div>
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" onClick={onDuplicate} aria-label={`Duplicate ${design.title}`}>
            <CopyIcon aria-hidden /> Duplicate
          </Button>
          <Button variant="ghost" size="sm" onClick={onDelete} aria-label={`Delete ${design.title}`}>
            <Trash2 aria-hidden /> Delete
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** Prompt + brand kit -> layout options -> editor; plus the list of saved designs. */
export function DesignHome() {
  const router = useRouter();
  const getOptions = useRequestOptions();
  const [sizes, setSizes] = React.useState<SizePreset[]>([]);
  const [templates, setTemplates] = React.useState<TemplateInfo[]>([]);
  const [kits, setKits] = React.useState<BrandKitInfo[]>([]);
  const [designs, setDesigns] = React.useState<DesignSummary[] | null>(null);
  const [loadError, setLoadError] = React.useState("");

  const [prompt, setPrompt] = React.useState("");
  const [size, setSize] = React.useState("square");
  const [kitId, setKitId] = React.useState("");
  const [useLlm, setUseLlm] = React.useState(true);
  const [result, setResult] = React.useState<GenerateResult | null>(null);
  const [busy, setBusy] = React.useState<string>("");
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    setLoadError("");
    try {
      const opts = await getOptions();
      const [t, k, d] = await Promise.all([listTemplates(opts), listBrandKits(opts), listDesigns(opts)]);
      setSizes(t.sizes);
      setTemplates(t.templates.filter((x) => !x.builtin));
      setKits(k.kits);
      setDesigns(d.designs);
      const firstBrand = k.kits.find((kit) => kit.has_brand);
      setKitId((current) => current || firstBrand?.id || "");
    } catch (err) {
      setLoadError(errorMessage(err));
      setDesigns([]);
    }
  }, [getOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const generate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (prompt.trim().length < 3) {
      setError("Describe what the design is for, for example: launch post for our habit tracker app.");
      return;
    }
    setBusy("generate");
    try {
      const res = await generateDesigns(
        { prompt: prompt.trim(), size_preset: size, brand_kit_id: kitId || null, use_llm: useLlm },
        await getOptions(),
      );
      requestFonts(res.options.flatMap((o) => fontsIn(o.canvas)));
      setResult(res);
    } catch (err) {
      setResult(null);
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const open = async (body: Parameters<typeof createDesign>[0], tag: string) => {
    setBusy(tag);
    setError("");
    try {
      const doc = await createDesign(body, await getOptions());
      router.push(`/studio/design/${doc.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy("");
    }
  };

  const applyOption = (option: GenerateResult["options"][number]) =>
    result &&
    open(
      {
        title: result.copy.headline.slice(0, 80),
        size_preset: result.size_preset,
        canvas: option.canvas,
        template: option.template,
        brand_kit_id: result.brand.brand_kit_id,
        prompt: prompt.trim(),
      },
      `use:${option.template}`,
    );

  const remove = async (d: DesignSummary) => {
    if (!window.confirm(`Delete "${d.title}"? Exported images stay in your library.`)) return;
    try {
      await deleteDesign(d.id, await getOptions());
      setDesigns((list) => (list ?? []).filter((x) => x.id !== d.id));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const duplicate = async (d: DesignSummary) => {
    try {
      const copy = await duplicateDesign(d.id, await getOptions());
      setDesigns((list) => [copy, ...(list ?? [])]);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const selectedKit = kits.find((k) => k.id === kitId);

  return (
    <div className="space-y-10">
      <Card>
        <CardContent className="p-6">
          <form onSubmit={generate} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="design-prompt">What is this design for?</Label>
              <Textarea
                id="design-prompt"
                rows={3}
                maxLength={2000}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Launch post for our habit tracker app. Streak reminders and a home screen widget. Download on iOS."
              />
              <p className="text-xs text-muted-foreground">
                The layouts only use words and numbers you write here or that are in your brand kit.
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="design-size">Size</Label>
                <Select id="design-size" value={size} onChange={(e) => setSize(e.target.value)}>
                  {(sizes.length ? sizes : [{ id: "square", width: 1080, height: 1080 }]).map((s) => (
                    <option key={s.id} value={s.id}>
                      {SIZE_LABELS[s.id] ?? s.id} ({s.width}x{s.height})
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="design-kit">Brand kit</Label>
                <Select id="design-kit" value={kitId} onChange={(e) => setKitId(e.target.value)}>
                  <option value="">No brand kit (neutral colours)</option>
                  {kits.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.name}
                      {k.has_brand ? "" : " (no brand details)"}
                    </option>
                  ))}
                </Select>
                {kits.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    <Link href="/presets" className="underline">
                      Import a brand kit
                    </Link>{" "}
                    from your website to use its colours, fonts and logo.
                  </p>
                ) : null}
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
                  Tighten the copy with AI (not charged; falls back to your words)
                </label>
              </div>
            </div>
            {selectedKit ? (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>Using</span>
                {Object.entries(selectedKit.colors).map(([name, hex]) => (
                  <span key={name} className="flex items-center gap-1">
                    <span className="inline-block size-4 rounded border" style={{ background: hex }} aria-hidden />
                    {name}
                  </span>
                ))}
                <span>
                  {selectedKit.fonts.heading} / {selectedKit.fonts.body}
                </span>
              </div>
            ) : null}
            <ErrorText message={error} />
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={busy === "generate"}>
                {busy === "generate" ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
                Make layouts
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  open(
                    { title: "Blank design", size_preset: size, canvas: blankCanvas(), brand_kit_id: kitId || null },
                    "blank",
                  )
                }
              >
                <FilePlus2 aria-hidden /> Start blank
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {result ? (
        <section className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-semibold">Pick a layout</h2>
            <p className="text-xs text-muted-foreground">
              Copy written {result.copy_source === "llm" ? "with AI from your words" : "from your words"}
              {result.brand.has_brand ? ` in ${result.brand.name || "your brand"}'s colours` : ""}.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {result.options.map((option) => (
              <OptionCard
                key={option.template}
                option={option}
                result={result}
                busy={busy === `use:${option.template}`}
                onUse={() => void applyOption(option)}
                getOptions={getOptions}
              />
            ))}
          </div>
        </section>
      ) : null}

      {templates.length > 0 ? (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Your templates</h2>
          <div className="flex flex-wrap gap-2">
            {templates.map((t) => (
              <Button
                key={t.id ?? t.slug}
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  open({ title: t.name, size_preset: t.presets[0] ?? "square", template_id: t.id, canvas: null }, `tpl:${t.id}`)
                }
              >
                <LayoutTemplate aria-hidden /> {t.name}
              </Button>
            ))}
          </div>
        </section>
      ) : null}

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Your designs</h2>
        {loadError ? (
          <div className="space-y-2">
            <ErrorText message={loadError} />
            <Button variant="outline" size="sm" onClick={() => void load()}>
              Try again
            </Button>
          </div>
        ) : designs === null ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-60" />
            ))}
          </div>
        ) : designs.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No designs yet. Describe a post above and pick a layout to start.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {designs.map((d) => (
              <DesignCard key={d.id} design={d} onDuplicate={() => void duplicate(d)} onDelete={() => void remove(d)} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
