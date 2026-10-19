/**
 * Minimal TypeSafe "System One" (Jev) HTTP client — SERVER ONLY.
 *
 * Mirrors the shape of the reference client at `products/openjev/sdk/js-lite/src/client.ts`
 * (zero runtime deps, global `fetch`, bounded retries + timeout) but trimmed to
 * exactly what the Winning Hook Finder needs. The API key is NEVER read here from
 * a browser bundle: the caller (the API route) resolves it server-side and passes
 * it in, so `Authorization: Bearer <key>` only ever leaves the Worker.
 *
 * All questions in one `systemOne()` call run in parallel on the server and
 * cannot see each other's answers, so batch every question for a variant into a
 * single call.
 */

// ---- Question builders (produce the exact wire shape /v1/systemone expects) --

export type Instructions = string | Record<string, unknown> | readonly unknown[];

export interface NoulQuestion {
  readonly type: "noul";
  readonly instructions: Instructions;
  readonly criteria?: { readonly true: string; readonly false: string };
}
export interface ChoiceQuestion {
  readonly type: "choice";
  readonly instructions: Instructions;
  readonly criteria: Readonly<Record<string, string | null>>;
}
export interface ScoreQuestion {
  readonly type: "score";
  readonly instructions: Instructions;
  readonly criteria: readonly string[];
}
export type Question = NoulQuestion | ChoiceQuestion | ScoreQuestion;

/** Whether a condition holds — answer is p(yes) in 0..1. */
export function noul(
  instructions: Instructions,
  criteria?: { true: string; false: string },
): NoulQuestion {
  return criteria ? { type: "noul", instructions, criteria } : { type: "noul", instructions };
}

/** Pick one of a fixed, code-supplied set of options (the model never invents). */
export function choice(
  instructions: Instructions,
  options: Readonly<Record<string, string | null>>,
): ChoiceQuestion {
  return { type: "choice", instructions, criteria: { ...options } };
}

/** Position along an ordered scale; `levels` are lowest → highest. */
export function score(instructions: Instructions, levels: readonly string[]): ScoreQuestion {
  return { type: "score", instructions, criteria: [...levels] };
}

// ---- Answer shapes (as returned by /v1/systemone) --------------------------

export interface NoulAnswer {
  readonly type: "noul";
  readonly noul: number;
}
export interface ChoiceAnswer {
  readonly type: "choice";
  readonly choice: string;
  readonly probabilities: Readonly<Record<string, number>>;
  readonly confidence: number;
}
export interface ScoreAnswer {
  readonly type: "score";
  readonly score: number;
  readonly legend: Readonly<Record<string, string>>;
  readonly probabilities: Readonly<Record<string, number>>;
  readonly confidence: number;
}
export type Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer;

export interface SystemOneResponse<K extends string = string> {
  readonly model: string;
  readonly answers: Readonly<Record<K, Answer>>;
  readonly usage?: { readonly input_tokens: number; readonly output_tokens: number };
}

export function isNoul(a: Answer | undefined): a is NoulAnswer {
  return !!a && a.type === "noul";
}
export function isChoice(a: Answer | undefined): a is ChoiceAnswer {
  return !!a && a.type === "choice";
}
export function isScore(a: Answer | undefined): a is ScoreAnswer {
  return !!a && a.type === "score";
}

/**
 * Composite a set of independently-judged Score dimensions into one 0..1 value.
 * Weights are applied HERE (never baked into the question) so retuning them does
 * not require re-running inference. Each dimension is normalized by its top level
 * index. A negative weight is allowed (e.g. to penalize a "slop" dimension).
 */
export function compositeScore(
  dims: ReadonlyArray<{ answer: ScoreAnswer; weight: number }>,
): number {
  let weightedSum = 0;
  let totalWeight = 0;
  for (const d of dims) {
    const norm = normalizeScore(d.answer);
    weightedSum += norm * d.weight;
    totalWeight += Math.abs(d.weight);
  }
  return totalWeight > 0 ? clamp01(weightedSum / totalWeight + slack(dims)) : 0;
}

/** Normalize a Score answer to 0..1 using its own legend's top index. */
export function normalizeScore(answer: ScoreAnswer): number {
  const keys = Object.keys(answer.legend).map(Number).filter(Number.isFinite);
  const max = keys.length ? Math.max(...keys) : 0;
  return max > 0 ? clamp01(answer.score / max) : 0;
}

/**
 * When a dimension carries a negative weight (a penalty like "slop"), a raw
 * weighted mean can push the composite below 0 for a perfectly-slop-free but
 * weak hook. `slack` re-centers penalties so `0 slop` contributes its full
 * positive share rather than nothing. Kept tiny + pure.
 */
function slack(dims: ReadonlyArray<{ answer: ScoreAnswer; weight: number }>): number {
  let negWeight = 0;
  let total = 0;
  for (const d of dims) {
    total += Math.abs(d.weight);
    if (d.weight < 0) negWeight += Math.abs(d.weight);
  }
  return total > 0 ? negWeight / total : 0;
}

export function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return n < 0 ? 0 : n > 1 ? 1 : n;
}

// ---- The client ------------------------------------------------------------

export interface TypeSafeClientOptions {
  readonly apiKey: string;
  readonly baseUrl?: string;
  readonly model?: string;
  readonly maxRetries?: number;
  readonly backoffMs?: number;
  readonly timeoutMs?: number;
  readonly fetchImpl?: typeof fetch;
}

export class TypeSafeError extends Error {
  readonly status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "TypeSafeError";
    if (status !== undefined) this.status = status;
  }
}

const DEFAULT_BASE_URL = "https://api.typesafe.ai/v1";
const DEFAULT_MODEL = "jev-latest";
const RETRYABLE = new Set([429, 500, 502, 503, 504, 529]);

export class TypeSafeClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly model: string;
  private readonly maxRetries: number;
  private readonly backoffMs: number;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: TypeSafeClientOptions) {
    if (!opts.apiKey) {
      throw new TypeSafeError("TypeSafe API key is required (server resolves it, never the browser).");
    }
    this.apiKey = opts.apiKey;
    this.baseUrl = (opts.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.model = opts.model ?? DEFAULT_MODEL;
    this.maxRetries = opts.maxRetries ?? 2;
    this.backoffMs = opts.backoffMs ?? 400;
    this.timeoutMs = opts.timeoutMs ?? 20_000;
    const impl = opts.fetchImpl ?? globalThis.fetch;
    if (typeof impl !== "function") {
      throw new TypeSafeError("global fetch is unavailable in this runtime.");
    }
    this.fetchImpl = impl;
  }

  /** Ask one batch of typed questions over one piece of state. */
  async systemOne<K extends string>(req: {
    state: unknown;
    questions: Record<K, Question>;
    signal?: AbortSignal;
  }): Promise<SystemOneResponse<K>> {
    const payload = JSON.stringify({
      state: req.state,
      model: this.model,
      questions: req.questions,
    });

    let lastError: unknown;
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      try {
        const res = await this.fetchImpl(`${this.baseUrl}/systemone`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${this.apiKey}`,
          },
          body: payload,
          signal: req.signal ?? controller.signal,
        });
        if (res.ok) {
          return (await res.json()) as SystemOneResponse<K>;
        }
        if (RETRYABLE.has(res.status) && attempt < this.maxRetries) {
          lastError = new TypeSafeError(`Retryable HTTP ${res.status}`, res.status);
          await sleep(this.backoffDelay(attempt, res.headers.get("retry-after")));
          continue;
        }
        throw new TypeSafeError(`TypeSafe request failed: HTTP ${res.status}`, res.status);
      } catch (err) {
        if (err instanceof TypeSafeError && err.status !== undefined) throw err;
        lastError = err;
        if (attempt < this.maxRetries) {
          await sleep(this.backoffDelay(attempt, null));
          continue;
        }
        throw new TypeSafeError(`TypeSafe request failed: ${errText(err)}`);
      } finally {
        clearTimeout(timer);
      }
    }
    throw new TypeSafeError(`TypeSafe request failed: ${errText(lastError)}`);
  }

  private backoffDelay(attempt: number, retryAfter: string | null): number {
    if (retryAfter) {
      const secs = Number(retryAfter);
      if (Number.isFinite(secs) && secs >= 0) return secs * 1000;
    }
    const base = this.backoffMs * 2 ** attempt;
    return Math.round(base * (0.5 + Math.random() * 0.5));
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
