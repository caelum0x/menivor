/**
 * Brand fonts: loaded from Google Fonts (free, no account) when the family
 * exists there; otherwise the browser falls back to system fonts. Fonts are
 * awaited before measuring or exporting so text wraps with real metrics.
 */

import type { Canvas } from "./types";

const SYSTEM = new Set(["system-ui", "sans-serif", "serif", "monospace", "Arial", "Helvetica", "Georgia"]);
const requested = new Set<string>();

export function fontsIn(canvas: Canvas): string[] {
  const set = new Set<string>();
  for (const page of canvas.pages) {
    for (const layer of page.layers) if (layer.type === "text") set.add(layer.props.fontFamily);
  }
  return [...set];
}

function safeFamily(name: string): string | null {
  return /^[A-Za-z0-9 -]{1,60}$/.test(name) ? name.trim() : null;
}

export function requestFonts(families: string[]): void {
  if (typeof document === "undefined") return;
  const wanted = families.map(safeFamily).filter((f): f is string => !!f && !SYSTEM.has(f) && !requested.has(f));
  if (wanted.length === 0) return;
  for (const f of wanted) requested.add(f);
  const query = wanted.map((f) => `family=${encodeURIComponent(f).replace(/%20/g, "+")}:ital,wght@0,400;0,700;1,400;1,700`).join("&");
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = `https://fonts.googleapis.com/css2?${query}&display=swap`;
  document.head.appendChild(link);
}

/** Resolve when the given families are ready (or after a short timeout). */
export async function fontsReady(families: string[], timeoutMs = 4000): Promise<void> {
  if (typeof document === "undefined" || !("fonts" in document)) return;
  requestFonts(families);
  const loads = families.flatMap((f) => [
    document.fonts.load(`400 32px "${f}"`),
    document.fonts.load(`700 32px "${f}"`),
  ]);
  await Promise.race([
    Promise.allSettled(loads),
    new Promise((resolve) => setTimeout(resolve, timeoutMs)),
  ]);
}
