/** RenderSpec builder + invariant validation (mirror of `spec.py`). */

import type { RenderLayout, RenderSpec } from "./filtergraph.js";
import { AVATAR_LAYOUTS } from "./filtergraph.js";

const LAYOUTS: ReadonlySet<RenderLayout> = new Set<RenderLayout>([
  "captions_only",
  "pip",
  "split",
  "hook_intro",
]);

const DEFAULT_DIAMETER = 480;
const DEFAULT_MARGIN = 48;

export interface MakeSpecOptions {
  width?: number;
  height?: number;
  fps?: number;
  layout?: RenderLayout;
  avatarInput?: number;
  diameter?: number;
  margin?: number;
  captionAss?: string;
  narration?: number;
  bgm?: number;
}

export function makeSpec(opts: MakeSpecOptions = {}): RenderSpec {
  const layout: RenderLayout = opts.layout ?? "captions_only";
  const spec: RenderSpec = {
    output: { width: opts.width ?? 1080, height: opts.height ?? 1920, fps: opts.fps ?? 30 },
    layout,
  };
  const diameter = opts.diameter ?? DEFAULT_DIAMETER;
  const margin = opts.margin ?? DEFAULT_MARGIN;
  if (AVATAR_LAYOUTS.has(layout)) {
    spec.avatar = { input: opts.avatarInput ?? 1, diameter, margin };
  } else if (opts.avatarInput !== undefined) {
    spec.avatar = { input: opts.avatarInput, diameter, margin };
  }
  if (opts.captionAss) spec.caption_ass = opts.captionAss;
  if (opts.narration !== undefined) {
    spec.audio = { narration: opts.narration };
    if (opts.bgm !== undefined) spec.audio.bgm = opts.bgm;
  }
  return spec;
}

/** Return a list of invariant violations (empty = valid). */
export function validateSpec(spec: RenderSpec): string[] {
  const errors: string[] = [];
  const out = spec.output ?? ({} as RenderSpec["output"]);
  for (const k of ["width", "height", "fps"] as const) {
    const v = out?.[k];
    if (!Number.isInteger(v) || (v as number) <= 0) errors.push(`output.${k} must be a positive int`);
  }

  const layout = spec.layout ?? "captions_only";
  if (!LAYOUTS.has(layout)) errors.push(`layout must be one of ${[...LAYOUTS].sort().join(",")}`);

  const avatar = spec.avatar;
  if (AVATAR_LAYOUTS.has(layout) && (!avatar || !Number.isInteger(avatar.input))) {
    errors.push(`layout ${layout} requires avatar.input (an int)`);
  }
  if (avatar) {
    for (const k of ["diameter", "margin"] as const) {
      const v = avatar[k];
      if (v !== undefined && (!Number.isInteger(v) || (v as number) < 0)) {
        errors.push(`avatar.${k} must be a non-negative int`);
      }
    }
  }

  if (spec.audio) {
    if (!Number.isInteger(spec.audio.narration)) errors.push("audio.narration must be an int");
    if (spec.audio.bgm !== undefined && !Number.isInteger(spec.audio.bgm)) {
      errors.push("audio.bgm must be an int");
    }
  }
  return errors;
}
