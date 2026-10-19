"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Circle,
  Download,
  ImagePlus,
  Loader2,
  Minus,
  Plus,
  Redo2,
  Save,
  Sparkles,
  Square,
  Trash2,
  Type,
  Undo2,
  CalendarClock,
  LayoutTemplate,
  Files,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { exportDesign, generateAiImage, getDesign, listBrandKits, saveAsTemplate, saveDesign, uploadDesignImage } from "./api";
import {
  addLayer,
  addPage,
  duplicateLayer,
  imageLayerFor,
  moveLayerOrder,
  removeLayer,
  removePage,
  shapeLayer,
  textLayer,
  updateLayer,
  updatePage,
  updateProps,
} from "./canvas-ops";
import { fontsIn, fontsReady } from "./fonts";
import { ColorField, Inspector } from "./Inspector";
import { PageView, imageKeys, imageUrlFor, useImageUrls } from "./PageView";
import { renderPageToPng } from "./render";
import { SchedulePanel } from "./SchedulePanel";
import { ErrorText, errorMessage, useRequestOptions } from "./shared";
import { snapBox, type Box } from "./snap";
import { SIZE_LABELS, type BrandKitInfo, type Canvas, type DesignDoc, type Layer } from "./types";
import { useHistory } from "./use-history";

const AUTOSAVE_MS = 2500;
const SNAP_PX = 8; // screen pixels

type Corner = "nw" | "ne" | "sw" | "se";

interface DragState {
  mode: "move" | Corner;
  id: string;
  startX: number;
  startY: number;
  box: Box;
  aspect: number;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read the file."));
    reader.readAsDataURL(file);
  });
}

function useStageScale(ref: React.RefObject<HTMLDivElement | null>, width: number, height: number): number {
  const [scale, setScale] = React.useState(0.4);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const w = el.clientWidth - 32;
      const h = Math.max(320, window.innerHeight - 260);
      setScale(Math.max(0.05, Math.min(w / width, h / height, 1)));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    window.addEventListener("resize", update);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [ref, width, height]);
  return scale;
}

export function DesignEditor({ id }: { id: string }) {
  const getOptions = useRequestOptions();
  const [doc, setDoc] = React.useState<DesignDoc | null>(null);
  const [loadError, setLoadError] = React.useState("");
  const [kit, setKit] = React.useState<BrandKitInfo | null>(null);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const opts = await getOptions();
        const d = await getDesign(id, opts);
        if (!alive) return;
        setDoc(d);
        if (d.brand_kit_id) {
          const kits = await listBrandKits(opts).catch(() => ({ kits: [] as BrandKitInfo[] }));
          if (alive) setKit(kits.kits.find((k) => k.id === d.brand_kit_id) ?? null);
        }
      } catch (err) {
        if (alive) setLoadError(errorMessage(err));
      }
    })();
    return () => {
      alive = false;
    };
  }, [id, getOptions]);

  if (loadError) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <ErrorText message={loadError} />
          <Button asChild variant="outline" size="sm">
            <Link href="/studio/design">Back to Design Studio</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }
  if (!doc) {
    return (
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Skeleton className="h-[60vh]" />
        <Skeleton className="h-[60vh]" />
      </div>
    );
  }
  return <Editor initial={doc} kit={kit} getOptions={getOptions} />;
}

function Editor({ initial, kit, getOptions }: { initial: DesignDoc; kit: BrandKitInfo | null; getOptions: () => Promise<{ token?: string }> }) {
  const [doc, setDoc] = React.useState(initial);
  const history = useHistory<Canvas>(initial.canvas);
  const canvas = history.value;
  const [title, setTitle] = React.useState(initial.title);
  const [pageIndex, setPageIndex] = React.useState(0);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [guides, setGuides] = React.useState<{ x: number[]; y: number[] }>({ x: [], y: [] });
  const [saveState, setSaveState] = React.useState<"saved" | "dirty" | "saving" | "error">("saved");
  const [busy, setBusy] = React.useState<string>("");
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [fontsVersion, setFontsVersion] = React.useState(0);
  const [aiPrompt, setAiPrompt] = React.useState("");
  const [showAi, setShowAi] = React.useState(false);
  const [showSchedule, setShowSchedule] = React.useState(false);
  const stageRef = React.useRef<HTMLDivElement>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const textRef = React.useRef<HTMLTextAreaElement>(null);
  const dragRef = React.useRef<DragState | null>(null);
  const savedRef = React.useRef<{ canvas: Canvas; title: string }>({ canvas: initial.canvas, title: initial.title });

  const W = doc.width;
  const H = doc.height;
  const scale = useStageScale(stageRef, W, H);
  const page = canvas.pages[Math.min(pageIndex, canvas.pages.length - 1)] ?? canvas.pages[0];
  const safePage = Math.min(pageIndex, canvas.pages.length - 1);
  const selected = page?.layers.find((l) => l.id === selectedId) ?? null;
  const urls = useImageUrls(imageKeys(canvas.pages), getOptions);

  const swatches = React.useMemo(() => {
    const set = new Set<string>();
    if (kit) Object.values(kit.colors).forEach((c) => set.add(c));
    ["#ffffff", "#000000"].forEach((c) => set.add(c));
    return [...set];
  }, [kit]);
  const brandFonts = React.useMemo(() => (kit ? [...new Set([kit.fonts.heading, kit.fonts.body])] : []), [kit]);
  const inkColor = kit?.colors.dark ?? "#111111";
  const shapeColor = kit?.colors.accent ?? "#f59e0b";
  const textFont = kit?.fonts.heading ?? "Inter";

  // Web fonts: load, then re-wrap text once metrics are real.
  const fontKey = fontsIn(canvas).join("|");
  React.useEffect(() => {
    let alive = true;
    void fontsReady(fontKey ? fontKey.split("|") : []).then(() => alive && setFontsVersion((v) => v + 1));
    return () => {
      alive = false;
    };
  }, [fontKey]);

  // Dirty tracking + autosave.
  const dirty = canvas !== savedRef.current.canvas || title !== savedRef.current.title;
  const save = React.useCallback(async (): Promise<boolean> => {
    const snapshot = { canvas, title };
    setSaveState("saving");
    try {
      const updated = await saveDesign(doc.id, { title: snapshot.title, canvas: snapshot.canvas }, await getOptions());
      savedRef.current = snapshot;
      setDoc((d) => ({ ...d, ...updated, canvas: d.canvas }));
      setSaveState("saved");
      return true;
    } catch (err) {
      setSaveState("error");
      setError(errorMessage(err));
      return false;
    }
  }, [canvas, title, doc.id, getOptions]);

  React.useEffect(() => {
    if (!dirty) return;
    setSaveState((s) => (s === "saving" ? s : "dirty"));
    const t = setTimeout(() => void save(), AUTOSAVE_MS);
    return () => clearTimeout(t);
  }, [dirty, save]);

  React.useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // Layer mutations.
  const mutate = (next: Canvas, merge = false) => history.set(next, { merge });
  const patchSelected = (patch: Partial<Layer>) => selected && mutate(updateLayer(canvas, safePage, selected.id, patch));
  const propsSelected = (props: Record<string, unknown>) =>
    selected && mutate(updateProps(canvas, safePage, selected.id, props as Partial<Layer["props"]>));
  const deleteSelected = () => {
    if (!selected) return;
    mutate(removeLayer(canvas, safePage, selected.id));
    setSelectedId(null);
  };
  const duplicateSelected = () => {
    if (!selected) return;
    const out = duplicateLayer(canvas, safePage, selected.id);
    mutate(out.canvas);
    setSelectedId(out.id);
  };
  const add = (layer: Layer) => {
    mutate(addLayer(canvas, safePage, layer));
    setSelectedId(layer.id);
  };

  // Keyboard shortcuts (ignored while typing in a field).
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable)) return;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) history.redo();
        else history.undo();
        return;
      }
      if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        history.redo();
        return;
      }
      if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void save();
        return;
      }
      if (!selected) return;
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        deleteSelected();
      } else if (mod && e.key.toLowerCase() === "d") {
        e.preventDefault();
        duplicateSelected();
      } else if (e.key.startsWith("Arrow") && !selected.locked) {
        e.preventDefault();
        const step = e.shiftKey ? 10 : 1;
        const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
        const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
        mutate(updateLayer(canvas, safePage, selected.id, { x: selected.x + dx, y: selected.y + dy }));
      } else if (e.key === "Escape") {
        setSelectedId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Pointer drag: move + corner resize with snap guides.
  const startDrag = (e: React.PointerEvent, layer: Layer, mode: DragState["mode"]) => {
    e.stopPropagation();
    setSelectedId(layer.id);
    if (layer.locked) return;
    e.preventDefault();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    history.checkpoint();
    dragRef.current = {
      mode,
      id: layer.id,
      startX: e.clientX,
      startY: e.clientY,
      box: { x: layer.x, y: layer.y, width: layer.width, height: layer.height },
      aspect: layer.width / Math.max(1, layer.height),
    };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag || !page) return;
    const dx = (e.clientX - drag.startX) / scale;
    const dy = (e.clientY - drag.startY) / scale;
    const others = page.layers.filter((l) => l.id !== drag.id && !l.hidden);
    const threshold = SNAP_PX / scale;
    let box: Box;
    if (drag.mode === "move") {
      const moved = { ...drag.box, x: drag.box.x + dx, y: drag.box.y + dy };
      const snapped = snapBox(moved, others, { width: W, height: H }, threshold);
      box = { ...moved, x: snapped.x, y: snapped.y };
      setGuides({ x: snapped.guidesX, y: snapped.guidesY });
    } else {
      const { x, y, width, height } = drag.box;
      const west = drag.mode === "nw" || drag.mode === "sw";
      const north = drag.mode === "nw" || drag.mode === "ne";
      let w = Math.max(10, width + (west ? -dx : dx));
      let h = Math.max(10, height + (north ? -dy : dy));
      if (e.shiftKey) h = w / drag.aspect;
      box = { x: west ? x + width - w : x, y: north ? y + height - h : y, width: w, height: h };
      setGuides({ x: [], y: [] });
    }
    const rounded = { x: Math.round(box.x), y: Math.round(box.y), width: Math.round(box.width), height: Math.round(box.height) };
    history.set((c) => updateLayer(c, safePage, drag.id, rounded), { merge: true });
  };

  const endDrag = () => {
    dragRef.current = null;
    setGuides({ x: [], y: [] });
  };

  // Images.
  const onUpload = async (file: File | undefined) => {
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) {
      setError("Use a PNG, JPEG or WebP image.");
      return;
    }
    if (file.size > 10_000_000) {
      setError("Images must be 10 MB or smaller.");
      return;
    }
    setBusy("upload");
    setError("");
    try {
      const stored = await uploadDesignImage(await readFileAsDataUrl(file), await getOptions());
      add(imageLayerFor(stored.key, stored.width, stored.height, W, H));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const onAiImage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (aiPrompt.trim().length < 3) {
      setError("Describe the image in a few words.");
      return;
    }
    setBusy("ai");
    setError("");
    try {
      const stored = await generateAiImage(doc.id, aiPrompt.trim(), await getOptions());
      add(imageLayerFor(stored.key, stored.width, stored.height, W, H));
      setDoc((d) => ({ ...d, used_ai_image: true }));
      setShowAi(false);
      setAiPrompt("");
      if (stored.cost_micros) setNotice(`Image added. Charged ${(stored.cost_micros / 1_000_000).toFixed(2)} USD to your wallet.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  // Export: save, render every page in the browser, store PNGs.
  const onExport = async () => {
    setBusy("export");
    setError("");
    setNotice("");
    try {
      if (dirty && !(await save())) return;
      await fontsReady(fontsIn(canvas));
      const source = (key: string) => imageUrlFor(key, getOptions);
      const pngs: string[] = [];
      for (const p of canvas.pages) pngs.push(await renderPageToPng(p, W, H, source));
      const updated = await exportDesign(doc.id, pngs, await getOptions());
      setDoc((d) => ({ ...d, ...updated, canvas: d.canvas }));
      setNotice(`Exported ${pngs.length} PNG${pngs.length > 1 ? "s" : ""} to your library.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const onSaveTemplate = async () => {
    const name = window.prompt("Template name", title)?.trim();
    if (!name) return;
    try {
      if (dirty && !(await save())) return;
      await saveAsTemplate(doc.id, name, await getOptions());
      setNotice(`Saved "${name}" to your templates.`);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const overlay = (
    <>
      {selected && !selected.hidden ? (
        <div
          className="pointer-events-none absolute"
          style={{ left: selected.x, top: selected.y, width: selected.width, height: selected.height, transform: selected.rotation ? `rotate(${selected.rotation}deg)` : undefined }}
        >
          {!selected.locked
            ? (["nw", "ne", "sw", "se"] as Corner[]).map((corner) => {
                const size = 14 / scale;
                return (
                  <div
                    key={corner}
                    role="presentation"
                    className="pointer-events-auto absolute rounded-sm border border-white bg-blue-500"
                    style={{
                      width: size,
                      height: size,
                      left: corner.endsWith("w") ? -size / 2 : undefined,
                      right: corner.endsWith("e") ? -size / 2 : undefined,
                      top: corner.startsWith("n") ? -size / 2 : undefined,
                      bottom: corner.startsWith("s") ? -size / 2 : undefined,
                      cursor: corner === "nw" || corner === "se" ? "nwse-resize" : "nesw-resize",
                    }}
                    onPointerDown={(e) => startDrag(e, selected, corner)}
                  />
                );
              })
            : null}
        </div>
      ) : null}
      {guides.x.map((x) => (
        <div key={`gx${x}`} className="pointer-events-none absolute top-0 bg-pink-500" style={{ left: x, width: 1 / scale, height: H }} />
      ))}
      {guides.y.map((y) => (
        <div key={`gy${y}`} className="pointer-events-none absolute left-0 bg-pink-500" style={{ top: y, height: 1 / scale, width: W }} />
      ))}
    </>
  );

  const saveLabel = { saved: "Saved", dirty: "Unsaved changes", saving: "Saving", error: "Not saved" }[saveState];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button asChild variant="ghost" size="sm">
          <Link href="/studio/design">
            <ArrowLeft aria-hidden /> Designs
          </Link>
        </Button>
        <Input aria-label="Design title" className="h-9 max-w-xs" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
        <Badge variant="outline">{SIZE_LABELS[doc.size_preset] ?? doc.size_preset} {W}x{H}</Badge>
        <span className={cn("text-xs", saveState === "error" ? "text-destructive" : "text-muted-foreground")} aria-live="polite">
          {saveLabel}
        </span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => void save()} disabled={saveState === "saving" || !dirty}>
            <Save aria-hidden /> Save
          </Button>
          <Button variant="outline" size="sm" onClick={() => void onSaveTemplate()}>
            <LayoutTemplate aria-hidden /> Save as template
          </Button>
          <Button size="sm" onClick={() => void onExport()} disabled={busy === "export"}>
            {busy === "export" ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />}
            Export PNG
          </Button>
          <Button variant="secondary" size="sm" disabled={doc.exports.length === 0 || dirty} title={doc.exports.length === 0 ? "Export first" : undefined} onClick={() => setShowSchedule((v) => !v)}>
            <CalendarClock aria-hidden /> Schedule
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1 rounded-md border p-1">
        <Button variant="ghost" size="sm" onClick={() => add(textLayer(W, H, textFont, inkColor))}>
          <Type aria-hidden /> Text
        </Button>
        <Button variant="ghost" size="sm" onClick={() => add(shapeLayer("rect", W, H, shapeColor))}>
          <Square aria-hidden /> Rectangle
        </Button>
        <Button variant="ghost" size="sm" onClick={() => add(shapeLayer("ellipse", W, H, shapeColor))}>
          <Circle aria-hidden /> Circle
        </Button>
        <Button variant="ghost" size="sm" onClick={() => add(shapeLayer("line", W, H, inkColor))}>
          <Minus aria-hidden /> Line
        </Button>
        <Button variant="ghost" size="sm" onClick={() => fileRef.current?.click()} disabled={busy === "upload"}>
          {busy === "upload" ? <Loader2 className="animate-spin" aria-hidden /> : <ImagePlus aria-hidden />} Image
        </Button>
        <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => void onUpload(e.target.files?.[0])} />
        <Button variant="ghost" size="sm" onClick={() => setShowAi((v) => !v)}>
          <Sparkles aria-hidden /> AI image
        </Button>
        <span className="mx-1 h-6 w-px bg-border" aria-hidden />
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={history.undo} disabled={!history.canUndo} aria-label="Undo" title="Undo (Ctrl+Z)">
          <Undo2 aria-hidden />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={history.redo} disabled={!history.canRedo} aria-label="Redo" title="Redo (Ctrl+Shift+Z)">
          <Redo2 aria-hidden />
        </Button>
      </div>

      {showAi ? (
        <Card>
          <CardContent className="p-4">
            <form className="flex flex-wrap items-center gap-2" onSubmit={onAiImage}>
              <Input
                aria-label="Describe the image"
                className="min-w-[240px] flex-1"
                maxLength={2000}
                value={aiPrompt}
                onChange={(e) => setAiPrompt(e.target.value)}
                placeholder="A phone on a desk showing a habit tracker, soft daylight"
              />
              <Button type="submit" size="sm" disabled={busy === "ai"}>
                {busy === "ai" ? <Loader2 className="animate-spin" aria-hidden /> : null}
                Generate
              </Button>
              <p className="w-full text-xs text-muted-foreground">
                AI images are charged to your wallet at the image model&apos;s price, only when the image is made. Everything else in Design Studio is free.
              </p>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {showSchedule ? (
        <SchedulePanel design={doc} getOptions={getOptions} onScheduled={(d) => setDoc((cur) => ({ ...cur, ...d, canvas: cur.canvas }))} onClose={() => setShowSchedule(false)} />
      ) : null}

      <ErrorText message={error} />
      {notice ? <p className="text-sm text-muted-foreground" aria-live="polite">{notice}</p> : null}

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-3">
          <div
            ref={stageRef}
            className="flex min-h-[320px] items-center justify-center rounded-md border bg-secondary/30 p-4"
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
          >
            {page ? (
              <div className="shadow-lg">
                <PageView
                  page={page}
                  width={W}
                  height={H}
                  scale={scale}
                  imageUrls={urls}
                  fontsVersion={fontsVersion}
                  selectedId={selectedId}
                  onLayerPointerDown={(e, layer) => startDrag(e, layer, "move")}
                  onBackgroundPointerDown={() => setSelectedId(null)}
                  overlay={overlay}
                />
              </div>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {canvas.pages.map((_, i) => (
              <Button key={i} size="sm" variant={i === safePage ? "secondary" : "ghost"} onClick={() => { setPageIndex(i); setSelectedId(null); }}>
                {canvas.pages.length > 1 ? `Slide ${i + 1}` : "Page"}
              </Button>
            ))}
            {canvas.pages.length < 10 ? (
              <>
                <Button size="sm" variant="ghost" onClick={() => { mutate(addPage(canvas, safePage)); setPageIndex(safePage + 1); }}>
                  <Plus aria-hidden /> Slide
                </Button>
                <Button size="sm" variant="ghost" onClick={() => { if (page) { mutate(addPage(canvas, safePage, page)); setPageIndex(safePage + 1); } }}>
                  <Files aria-hidden /> Duplicate slide
                </Button>
              </>
            ) : null}
            {canvas.pages.length > 1 ? (
              <Button size="sm" variant="ghost" onClick={() => { mutate(removePage(canvas, safePage)); setPageIndex(Math.max(0, safePage - 1)); setSelectedId(null); }}>
                <Trash2 aria-hidden /> Remove slide
              </Button>
            ) : null}
          </div>

          {doc.exports.length > 0 ? (
            <Card>
              <CardContent className="space-y-2 p-4">
                <p className="text-sm font-medium">
                  Last export{doc.status === "scheduled" ? " (queued for approval)" : ""}
                  {dirty ? <span className="ml-2 text-xs font-normal text-muted-foreground">Out of date: export again to include your changes.</span> : null}
                </p>
                <div className="flex flex-wrap gap-3">
                  {doc.exports.map((ex, i) =>
                    ex.url ? (
                      <a key={ex.key} href={ex.url} target="_blank" rel="noreferrer" className="text-sm text-primary underline">
                        Download page {i + 1}
                      </a>
                    ) : (
                      <span key={ex.key} className="text-sm text-muted-foreground">
                        Page {i + 1} saved (storage link unavailable)
                      </span>
                    ),
                  )}
                </div>
              </CardContent>
            </Card>
          ) : null}
        </div>

        <aside className="space-y-4">
          <Card>
            <CardContent className="space-y-4 p-4">
              {selected ? (
                <Inspector
                  key={selected.id}
                  layer={selected}
                  swatches={swatches}
                  brandFonts={brandFonts}
                  textRef={textRef}
                  onChange={patchSelected}
                  onProps={propsSelected}
                  onDelete={deleteSelected}
                  onDuplicate={duplicateSelected}
                  onOrder={(dir) => mutate(moveLayerOrder(canvas, safePage, selected.id, dir))}
                />
              ) : page ? (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground">Select a layer on the canvas to edit it.</p>
                  <ColorField label="Background" value={page.background} swatches={swatches} onChange={(v) => mutate(updatePage(canvas, safePage, (p) => ({ ...p, background: v })))} />
                </div>
              ) : null}
            </CardContent>
          </Card>
          {page ? (
            <Card>
              <CardContent className="space-y-1 p-4">
                <p className="mb-2 text-sm font-medium">Layers</p>
                {page.layers.length === 0 ? <p className="text-xs text-muted-foreground">No layers yet. Add text, a shape or an image.</p> : null}
                {[...page.layers].reverse().map((l) => (
                  <button
                    key={l.id}
                    type="button"
                    onClick={() => setSelectedId(l.id)}
                    onDoubleClick={() => l.type === "text" && textRef.current?.focus()}
                    className={cn(
                      "flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-secondary/60",
                      l.id === selectedId && "bg-secondary",
                    )}
                  >
                    <span className="truncate">{l.name}</span>
                    <span className="text-xs text-muted-foreground">{l.locked ? "locked" : l.type}</span>
                  </button>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
