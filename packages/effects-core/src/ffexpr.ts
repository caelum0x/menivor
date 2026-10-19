/**
 * FFmpeg-expression bridge (mirror of `reelforge_effects_core/ffexpr.py`).
 *
 * `kernels.ts` returns the numeric transform/filter params at a normalized time
 * `t` (the live preview). This module renders the SAME kernels as **FFmpeg filter
 * expression strings** (in a caller-supplied normalized-time sub-expression `tn`)
 * so the render executor (`app/services/compose/vfx.py`) can splice them into a
 * `scale=...:eval=frame` / `crop` / `rotate` chain and land the exact value the
 * preview showed — frame-accurate parity.
 *
 * Because the kernels are pure polynomial / exact-integer math (all intermediates
 * < 2**53), FFmpeg's `double` evaluation of these strings is bit-identical to the
 * numeric kernels — see {@link evaluate} and the parity harness.
 *
 * Only the whitelisted FFmpeg ops are used (`+ - * /`, `clip`, `if`, `lt`, `gte`,
 * `floor`, `min`, `max`, `abs`) so the output stays portable and {@link evaluate}
 * can model FFmpeg's semantics.
 */

const HASH = 2654435761; // Knuth multiplicative hash — matches keyframe.ts noise1
const MOD = 4294967296; // 2**32

// --- easing primitives -> FFmpeg expression strings (mirror easing) -------- //
export function clamp01Expr(tn: string): string {
  return `(clip((${tn}),0,1))`;
}

export function linearExpr(tn: string): string {
  return clamp01Expr(tn);
}

export function easeInOutExpr(tn: string): string {
  const t = clamp01Expr(tn);
  return `(if(lt(${t},0.5),2*${t}*${t},1-2*(1-${t})*(1-${t})))`;
}

export function peakExpr(tn: string): string {
  const t = clamp01Expr(tn);
  return `(4*${t}*(1-${t}))`;
}

/** Deterministic pseudo-noise in [-1,1]; modulo via `floor` to match Python `%`. */
export function noise1Expr(nExpr: string, seed = 0): string {
  const m = `(((${nExpr})+(${seed | 0}))*${HASH})`;
  const h = `(${m}-floor(${m}/${MOD})*${MOD})`;
  return `(${h}/${MOD}*2-1)`;
}

function roundExpr(x: string): string {
  // No round() in FFmpeg; floor(x+0.5) matches Python `int(round(t*1000))`.
  return `floor((${x})*1000+0.5)`;
}

function g(n: number): string {
  // Compact, precise numeric literal (mirrors Python's `:.9g`).
  return Number(n.toPrecision(9)).toString();
}

// --- camera kernels -> FFmpeg expression strings (mirror kernels) ---------- //
export function pushInZoomExpr(tn: string, p: { intensity?: number } = {}): string {
  const intensity = p.intensity ?? 0.3;
  return `(1+${g(intensity)}*${easeInOutExpr(tn)})`;
}

export interface KenBurnsExpr {
  zoom: string;
  x: string;
  y: string;
}

export function kenBurnsExpr(
  tn: string,
  p: { zoom?: number; pan_x?: number; pan_y?: number } = {},
): KenBurnsExpr {
  const zoom = p.zoom ?? 0.2;
  const panX = p.pan_x ?? 0.1;
  const panY = p.pan_y ?? 0.05;
  const lin = linearExpr(tn);
  return {
    zoom: `(1+${g(zoom)}*${lin})`,
    x: `(${g(panX)}*${lin})`,
    y: `(${g(panY)}*${lin})`,
  };
}

export interface HandheldExpr {
  dx: string;
  dy: string;
  rot: string;
}

export function handheldExpr(
  tn: string,
  p: { intensity?: number; seed?: number } = {},
): HandheldExpr {
  const intensity = p.intensity ?? 0.02;
  const seed = p.seed ?? 1;
  const n = roundExpr(clamp01Expr(tn));
  return {
    dx: `(${g(intensity)}*${noise1Expr(n, seed)})`,
    dy: `(${g(intensity)}*${noise1Expr(n, seed + 7)})`,
    rot: `(${g(intensity * 0.5)}*${noise1Expr(n, seed + 13)})`,
  };
}

// --- faithful numeric evaluator for the whitelisted FFmpeg subset ---------- //
type Tokens = { pos: number; src: string };

/**
 * Evaluate an FFmpeg expression string built by this module, using `variables`
 * (e.g. `{ t: 0.5 }`). Supports only the whitelisted ops/functions; throws on
 * anything else so it can never run arbitrary code. Mirrors the Python evaluator
 * and lets the parity harness prove expr === kernel without a real FFmpeg.
 */
export function evaluate(expr: string, variables: Record<string, number> = {}): number {
  const s: Tokens = { pos: 0, src: expr };

  const ws = () => {
    while (s.pos < s.src.length && s.src[s.pos] === " ") s.pos++;
  };

  const parseExpr = (): number => {
    let v = parseTerm();
    for (;;) {
      ws();
      const c = s.src[s.pos];
      if (c === "+") {
        s.pos++;
        v += parseTerm();
      } else if (c === "-") {
        s.pos++;
        v -= parseTerm();
      } else break;
    }
    return v;
  };

  const parseTerm = (): number => {
    let v = parseFactor();
    for (;;) {
      ws();
      const c = s.src[s.pos];
      if (c === "*") {
        s.pos++;
        v *= parseFactor();
      } else if (c === "/") {
        s.pos++;
        v /= parseFactor();
      } else break;
    }
    return v;
  };

  const funcs: Record<string, (a: number[]) => number> = {
    clip: (a) => Math.min(Math.max(a[0], a[1]), a[2]),
    if: (a) => (a[0] !== 0 ? a[1] : a.length > 2 ? a[2] : 0),
    lt: (a) => (a[0] < a[1] ? 1 : 0),
    lte: (a) => (a[0] <= a[1] ? 1 : 0),
    gt: (a) => (a[0] > a[1] ? 1 : 0),
    gte: (a) => (a[0] >= a[1] ? 1 : 0),
    eq: (a) => (a[0] === a[1] ? 1 : 0),
    floor: (a) => Math.floor(a[0]),
    min: (a) => Math.min(a[0], a[1]),
    max: (a) => Math.max(a[0], a[1]),
    abs: (a) => Math.abs(a[0]),
  };

  const parseFactor = (): number => {
    ws();
    const c = s.src[s.pos];
    if (c === "+") {
      s.pos++;
      return parseFactor();
    }
    if (c === "-") {
      s.pos++;
      return -parseFactor();
    }
    if (c === "(") {
      s.pos++;
      const v = parseExpr();
      ws();
      if (s.src[s.pos] !== ")") throw new Error("expected ')'");
      s.pos++;
      return v;
    }
    // number
    const numMatch = /^[0-9]*\.?[0-9]+([eE][+-]?[0-9]+)?/.exec(s.src.slice(s.pos));
    if (numMatch) {
      s.pos += numMatch[0].length;
      return Number(numMatch[0]);
    }
    // identifier -> function call or variable
    const idMatch = /^[A-Za-z_][A-Za-z0-9_]*/.exec(s.src.slice(s.pos));
    if (!idMatch) throw new Error(`unexpected token at ${s.pos}: ${s.src.slice(s.pos, s.pos + 8)}`);
    const id = idMatch[0];
    s.pos += id.length;
    ws();
    if (s.src[s.pos] === "(") {
      s.pos++;
      const args: number[] = [];
      ws();
      if (s.src[s.pos] !== ")") {
        args.push(parseExpr());
        ws();
        while (s.src[s.pos] === ",") {
          s.pos++;
          args.push(parseExpr());
          ws();
        }
      }
      if (s.src[s.pos] !== ")") throw new Error("expected ')'");
      s.pos++;
      const fn = funcs[id];
      if (!fn) throw new Error(`unsupported function: ${id}`);
      return fn(args);
    }
    if (id in variables) return variables[id];
    throw new Error(`unknown variable: ${id}`);
  };

  const result = parseExpr();
  ws();
  if (s.pos !== s.src.length) throw new Error(`trailing tokens at ${s.pos}`);
  return result;
}
