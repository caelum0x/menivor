/**
 * ASS document builder (mirror of `ass_builder.py`). `buildAss(words, style)`
 * produces a byte-identical ASS string to the Python port (golden `.ass` parity).
 */

import { hexToAss } from "./color.js";
import type { CaptionStyle } from "./style.js";
import { getPreset } from "./style.js";

export interface Word {
  text: string;
  start: number;
  end: number;
}

export const PLAY_RES_X = 1080;
export const PLAY_RES_Y = 1920;

const STYLE_FORMAT =
  "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, " +
  "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, " +
  "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding";
const EVENT_FORMAT = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text";

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Seconds → ASS `H:MM:SS.cc`. */
export function formatTime(seconds: number): string {
  const csTotal = Math.round(Math.max(0, seconds) * 100);
  const h = Math.floor(csTotal / 360000);
  const m = Math.floor((csTotal % 360000) / 6000);
  const s = Math.floor((csTotal % 6000) / 100);
  const cs = csTotal % 100;
  return `${h}:${pad2(m)}:${pad2(s)}.${pad2(cs)}`;
}

function styleLine(style: CaptionStyle): string {
  const bold = style.bold ? -1 : 0;
  return (
    `Style: Default,${style.font},${style.size},` +
    `${hexToAss(style.primary_hex)},${hexToAss(style.highlight_hex)},` +
    `${hexToAss(style.outline_hex)},&H00000000,` +
    `${bold},0,0,0,100,100,0,0,1,` +
    `${style.outline},${style.shadow},${style.alignment},60,60,${style.margin_v},1`
  );
}

function dialogueLine(group: Word[], style: CaptionStyle): string {
  const start = formatTime(group[0].start);
  const end = formatTime(group[group.length - 1].end);
  const parts = group.map((w) => {
    const durCs = Math.max(0, Math.round((w.end - w.start) * 100));
    const text = style.uppercase ? w.text.toUpperCase() : w.text;
    return `{\\k${durCs}}${text}`;
  });
  return `Dialogue: 0,${start},${end},Default,,0,0,0,,${parts.join(" ")}`;
}

/** Build a complete ASS document from word timestamps + a style. */
export function buildAss(words: Word[], style?: CaptionStyle): string {
  const s = style ?? getPreset("hormozi");
  const size = Math.max(1, Math.trunc(s.words_per_group));
  const lines: string[] = [
    "[Script Info]",
    "ScriptType: v4.00+",
    `PlayResX: ${PLAY_RES_X}`,
    `PlayResY: ${PLAY_RES_Y}`,
    "",
    "[V4+ Styles]",
    STYLE_FORMAT,
    styleLine(s),
    "",
    "[Events]",
    EVENT_FORMAT,
  ];
  for (let i = 0; i < words.length; i += size) {
    const group = words.slice(i, i + size);
    if (group.length) lines.push(dialogueLine(group, s));
  }
  return lines.join("\n") + "\n";
}
