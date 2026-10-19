/**
 * RenderSpec → FFmpeg `filter_complex` builder (mirror of `filtergraph.py`).
 * Pure, deterministic string assembly with stable pad labels — byte-identical to
 * the Python port (golden fixtures). No process spawning, no storage.
 *
 * The composition graph (`[comp]`) and the ducked-audio graph (`[aout]`) are
 * reproduced byte-for-byte from the executor (`compose_ffmpeg.py`): its layout
 * builders terminate at `[comp]` and `_build_audio_graph` at `[aout]`. The
 * executor's environment-specific caption-burn / watermark nodes (which escape an
 * absolute path + embed the render-time font dir) live past `[comp]` and are NOT
 * modelled here — `videoOutLabel` returns `[comp]` and the executor finishes from
 * there. Chroma / diameter / margin / loudnorm are the executor's shipping-path
 * defaults, baked as constants so no locale-sensitive number formatting is needed.
 */

export type RenderLayout = "captions_only" | "pip" | "split" | "hook_intro";

export interface RenderAvatar {
  input: number;
  diameter?: number;
  margin?: number;
}

export interface RenderSpec {
  output: { width: number; height: number; fps: number };
  layout?: RenderLayout;
  avatar?: RenderAvatar;
  caption_ass?: string;
  audio?: { narration: number; bgm?: number };
}

// Constants — each mirrors a compose_ffmpeg default (see filtergraph.py).
const CHROMA = "chromakey=0x00FF00:0.18:0.1";
const PIP_DIAMETER = 480;
const PIP_MARGIN = 48;
const HOOK = "3";
const DUCK = "sidechaincompress=threshold=0.03:ratio=8:attack=5:release=250";
const LOUDNORM = "loudnorm=I=-14:TP=-1:LRA=11";

export const AVATAR_LAYOUTS: ReadonlySet<RenderLayout> = new Set([
  "pip",
  "split",
  "hook_intro",
]);

interface ResolvedAvatar {
  input: number;
  diameter: number;
  margin: number;
}

function dims(spec: RenderSpec): [number, number] {
  const out = spec.output ?? ({} as RenderSpec["output"]);
  return [Math.trunc(out?.width ?? 1080), Math.trunc(out?.height ?? 1920)];
}

function resolveAvatar(spec: RenderSpec): ResolvedAvatar {
  const av = spec.avatar ?? ({ input: 1 } as RenderAvatar);
  return {
    input: Math.trunc(av.input ?? 1),
    diameter: Math.trunc(av.diameter ?? PIP_DIAMETER),
    margin: Math.trunc(av.margin ?? PIP_MARGIN),
  };
}

function circleGeq(radius: number): string {
  return (
    "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':" +
    `a='if(lte(hypot(X-${radius},Y-${radius}),${radius}),alpha(X,Y),0)'`
  );
}

function layoutBase(w: number, h: number): string {
  return (
    `[0:v]scale=${w}:${h}:force_original_aspect_ratio=increase,` +
    `crop=${w}:${h},setsar=1[comp]`
  );
}

function layoutPip(w: number, h: number, av: ResolvedAvatar): string {
  const d = av.diameter;
  const radius = Math.floor(d / 2);
  const ai = av.input;
  const x = Math.max(0, w - d - av.margin);
  const y = Math.max(0, h - d - av.margin);
  return [
    `[0:v]scale=${w}:${h}:force_original_aspect_ratio=increase,` +
      `crop=${w}:${h},setsar=1[bg]`,
    `[${ai}:v]${CHROMA},` +
      `scale=${d}:${d}:force_original_aspect_ratio=increase,` +
      `crop=${d}:${d},format=rgba,${circleGeq(radius)}[av]`,
    `[bg][av]overlay=x=${x}:y=${y}:format=auto[comp]`,
  ].join(";");
}

function layoutSplit(w: number, h: number, av: ResolvedAvatar): string {
  const half = Math.floor(h / 2);
  const ai = av.input;
  return [
    `[0:v]scale=${w}:${h}:force_original_aspect_ratio=increase,` +
      `crop=${w}:${h},setsar=1,split=2[s_top][s_bot]`,
    `[s_top]crop=${w}:${half}:0:0[top]`,
    `[s_bot]crop=${w}:${half}:0:${half}[botbg]`,
    `[${ai}:v]${CHROMA},` +
      `scale=${w}:${half}:force_original_aspect_ratio=increase,` +
      `crop=${w}:${half},setsar=1,format=rgba[botfg]`,
    "[botbg][botfg]overlay=0:0:format=auto[bot]",
    "[top][bot]vstack=inputs=2[comp]",
  ].join(";");
}

function layoutHookIntro(w: number, h: number, av: ResolvedAvatar): string {
  const d = av.diameter;
  const radius = Math.floor(d / 2);
  const ai = av.input;
  const x = Math.max(0, w - d - av.margin);
  const y = Math.max(0, h - d - av.margin);
  return [
    `[0:v]scale=${w}:${h}:force_original_aspect_ratio=increase,` +
      `crop=${w}:${h},setsar=1[bg]`,
    `[${ai}:v]${CHROMA},format=rgba,split=2[a_raw][b_raw]`,
    `[a_raw]scale=${w}:${h}:force_original_aspect_ratio=increase,` +
      `crop=${w}:${h},setsar=1[a_full]`,
    `[b_raw]scale=${d}:${d}:force_original_aspect_ratio=increase,` +
      `crop=${d}:${d},${circleGeq(radius)}[a_pip]`,
    `[bg][a_full]overlay=0:0:format=auto:enable='lt(t,${HOOK})'[tmp]`,
    `[tmp][a_pip]overlay=x=${x}:y=${y}:format=auto:enable='gte(t,${HOOK})'[comp]`,
  ].join(";");
}

/** Build the composition graph (video only, terminating in `[comp]`). */
export function buildVideoGraph(spec: RenderSpec): string {
  const [w, h] = dims(spec);
  switch (spec.layout) {
    case "pip":
      return layoutPip(w, h, resolveAvatar(spec));
    case "split":
      return layoutSplit(w, h, resolveAvatar(spec));
    case "hook_intro":
      return layoutHookIntro(w, h, resolveAvatar(spec));
    default:
      return layoutBase(w, h);
  }
}

/** Build the ducked-music + loudnorm audio graph (or `""` when no bgm). */
export function buildAudioGraph(spec: RenderSpec): string {
  const audio = spec.audio;
  if (!audio) return "";
  const bgm = audio.bgm;
  if (bgm === undefined || bgm === null) return "";
  const nar = Math.trunc(audio.narration);
  const b = Math.trunc(bgm);
  return [
    `[${nar}:a]asplit=2[vo][vo_key]`,
    `[${b}:a][vo_key]${DUCK}[duck]`,
    "[vo][duck]amix=inputs=2:duration=first:dropout_transition=0[premix]",
    `[premix]${LOUDNORM}[aout]`,
  ].join(";");
}

/** Build the FFmpeg `filter_complex` string for a spec (deterministic). */
export function buildFiltergraph(spec: RenderSpec): string {
  const parts: string[] = [buildVideoGraph(spec)];
  const audio = buildAudioGraph(spec);
  if (audio) parts.push(audio);
  return parts.join(";");
}

/** The composition video sink to continue from (always `[comp]`). */
export function videoOutLabel(_spec: RenderSpec): string {
  return "[comp]";
}

export function hasAudioOut(spec: RenderSpec): boolean {
  return Boolean(spec.audio && spec.audio.bgm !== undefined && spec.audio.bgm !== null);
}
