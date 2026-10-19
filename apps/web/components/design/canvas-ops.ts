/** Immutable canvas operations used by the editor (every op returns a new Canvas). */

import type { Canvas, Layer, Page } from "./types";

export function newId(): string {
  return Math.random().toString(36).slice(2, 14);
}

export function updatePage(canvas: Canvas, index: number, fn: (page: Page) => Page): Canvas {
  return { ...canvas, pages: canvas.pages.map((p, i) => (i === index ? fn(p) : p)) };
}

export function updateLayer(canvas: Canvas, pageIndex: number, id: string, patch: Partial<Layer> | ((l: Layer) => Layer)): Canvas {
  return updatePage(canvas, pageIndex, (page) => ({
    ...page,
    layers: page.layers.map((l) =>
      l.id === id ? (typeof patch === "function" ? patch(l) : ({ ...l, ...patch } as Layer)) : l,
    ),
  }));
}

export function updateProps<L extends Layer>(canvas: Canvas, pageIndex: number, id: string, props: Partial<L["props"]>): Canvas {
  return updateLayer(canvas, pageIndex, id, (l) => ({ ...l, props: { ...l.props, ...props } }) as Layer);
}

export function addLayer(canvas: Canvas, pageIndex: number, layer: Layer): Canvas {
  return updatePage(canvas, pageIndex, (page) => ({ ...page, layers: [...page.layers, layer] }));
}

export function removeLayer(canvas: Canvas, pageIndex: number, id: string): Canvas {
  return updatePage(canvas, pageIndex, (page) => ({ ...page, layers: page.layers.filter((l) => l.id !== id) }));
}

export function duplicateLayer(canvas: Canvas, pageIndex: number, id: string): { canvas: Canvas; id: string | null } {
  const page = canvas.pages[pageIndex];
  const src = page?.layers.find((l) => l.id === id);
  if (!src) return { canvas, id: null };
  const copy = { ...src, id: newId(), name: `${src.name} copy`, x: src.x + 24, y: src.y + 24 } as Layer;
  return { canvas: addLayer(canvas, pageIndex, copy), id: copy.id };
}

export function moveLayerOrder(canvas: Canvas, pageIndex: number, id: string, dir: "up" | "down" | "top" | "bottom"): Canvas {
  return updatePage(canvas, pageIndex, (page) => {
    const idx = page.layers.findIndex((l) => l.id === id);
    if (idx < 0) return page;
    const layers = [...page.layers];
    const [item] = layers.splice(idx, 1);
    if (!item) return page;
    const target =
      dir === "top" ? layers.length : dir === "bottom" ? 0 : dir === "up" ? Math.min(layers.length, idx + 1) : Math.max(0, idx - 1);
    layers.splice(target, 0, item);
    return { ...page, layers };
  });
}

export function addPage(canvas: Canvas, after: number, copyFrom?: Page): Canvas {
  const page: Page = copyFrom
    ? { ...copyFrom, layers: copyFrom.layers.map((l) => ({ ...l, id: newId() }) as Layer) }
    : { background: canvas.pages[after]?.background ?? "#ffffff", layers: [] };
  const pages = [...canvas.pages];
  pages.splice(after + 1, 0, page);
  return { ...canvas, pages };
}

export function removePage(canvas: Canvas, index: number): Canvas {
  if (canvas.pages.length <= 1) return canvas;
  return { ...canvas, pages: canvas.pages.filter((_, i) => i !== index) };
}

export function textLayer(width: number, height: number, font: string, color: string): Layer {
  const w = Math.round(width * 0.7);
  return {
    id: newId(),
    type: "text",
    name: "Text",
    x: Math.round((width - w) / 2),
    y: Math.round(height * 0.4),
    width: w,
    height: Math.round(height * 0.12),
    rotation: 0,
    opacity: 1,
    props: { text: "Your text", fontFamily: font, fontSize: Math.round(Math.min(width, height) * 0.06), fontWeight: 700, color, align: "center", lineHeight: 1.15 },
  };
}

export function shapeLayer(kind: "rect" | "ellipse" | "line", width: number, height: number, color: string): Layer {
  const s = Math.round(Math.min(width, height) * 0.3);
  const base = { id: newId(), x: Math.round((width - s) / 2), y: Math.round((height - s) / 2), rotation: 0, opacity: 1 };
  if (kind === "line") {
    return { ...base, type: "line", name: "Line", width: s * 2, height: 24, x: Math.round(width / 2 - s), props: { stroke: color, strokeWidth: 8 } };
  }
  if (kind === "ellipse") {
    return { ...base, type: "ellipse", name: "Circle", width: s, height: s, props: { fill: color, stroke: "", strokeWidth: 0 } };
  }
  return { ...base, type: "rect", name: "Rectangle", width: s, height: s, props: { fill: color, stroke: "", strokeWidth: 0, radius: 0 } };
}

export function imageLayerFor(key: string, imgW: number, imgH: number, width: number, height: number): Layer {
  const max = Math.min(width, height) * 0.6;
  const scale = Math.min(1, max / Math.max(imgW || 1, imgH || 1));
  const w = Math.max(40, Math.round((imgW || max) * scale));
  const h = Math.max(40, Math.round((imgH || max) * scale));
  return {
    id: newId(),
    type: "image",
    name: "Image",
    x: Math.round((width - w) / 2),
    y: Math.round((height - h) / 2),
    width: w,
    height: h,
    rotation: 0,
    opacity: 1,
    props: { key, fit: "cover", radius: 0 },
  };
}
