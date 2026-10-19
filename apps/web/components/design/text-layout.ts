/**
 * One text-wrapping routine for both the on-screen editor and the PNG export,
 * so what you see is what gets exported. Measurement uses a 2D canvas context
 * with the same font string the export draws with.
 */

import type { TextProps } from "./types";

let measureCtx: CanvasRenderingContext2D | null = null;

function ctx(): CanvasRenderingContext2D | null {
  if (measureCtx) return measureCtx;
  if (typeof document === "undefined") return null;
  measureCtx = document.createElement("canvas").getContext("2d");
  return measureCtx;
}

export function fontString(p: Pick<TextProps, "fontFamily" | "fontSize" | "fontWeight" | "italic">): string {
  const family = p.fontFamily.includes(" ") ? `"${p.fontFamily}"` : p.fontFamily;
  return `${p.italic ? "italic " : ""}${p.fontWeight} ${p.fontSize}px ${family}, system-ui, sans-serif`;
}

export function displayText(p: Pick<TextProps, "text" | "uppercase">): string {
  return p.uppercase ? p.text.toUpperCase() : p.text;
}

/** Break text into lines that fit `width` (explicit newlines are kept). */
export function wrapText(p: TextProps, width: number, context?: CanvasRenderingContext2D | null): string[] {
  const c = context ?? ctx();
  const text = displayText(p);
  if (!c) return text.split("\n");
  c.font = fontString(p);
  const spacing = p.letterSpacing ?? 0;
  const measure = (s: string) => c.measureText(s).width + Math.max(0, s.length - 1) * spacing;
  const out: string[] = [];
  for (const paragraph of text.split("\n")) {
    const words = paragraph.split(/\s+/).filter(Boolean);
    if (words.length === 0) {
      out.push("");
      continue;
    }
    let line = "";
    for (const word of words) {
      const candidate = line ? `${line} ${word}` : word;
      if (!line || measure(candidate) <= width) {
        line = candidate;
        continue;
      }
      out.push(line);
      line = word;
    }
    // Hard-break a single word longer than the box.
    while (measure(line) > width && line.length > 1) {
      let cut = line.length - 1;
      while (cut > 1 && measure(line.slice(0, cut)) > width) cut -= 1;
      out.push(line.slice(0, cut));
      line = line.slice(cut);
    }
    out.push(line);
  }
  return out;
}
