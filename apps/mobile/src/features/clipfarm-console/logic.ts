/**
 * Pure, side-effect-free helpers for the Clipfarm console.
 *
 * Everything impure (fetch, session, navigation) lives in the Screen; this
 * module is pure so it is trivially unit-testable. It shapes free-text creator
 * input into the typed request bodies `lib/series.ts` sends, mints the
 * `Idempotency-Key` the trigger endpoints require, and formats the runner's
 * result summaries for display.
 */

import type {
  ChannelRunView,
  RunChannelInput,
  RunSummary,
  ScheduleSummary,
  SourceItemInput,
} from "@/lib/series";

/** Default aspect the runner falls back to when none is supplied. */
export const DEFAULT_ASPECT = "9:16";

/** Cross-post platforms the console offers as pacing targets. */
export const PLATFORM_OPTIONS = [
  "tiktok",
  "instagram",
  "youtube_shorts",
] as const;

export type PlatformOption = (typeof PLATFORM_OPTIONS)[number];

/**
 * Mint a stable idempotency key for a trigger submit. The backend REQUIRES this
 * header on both POST endpoints, so a caller retaining the key across an
 * ambiguous transport retry can never double-trigger a channel.
 */
export function newIdempotencyKey(scope: "run" | "schedule"): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `clipfarm-${scope}-${Date.now().toString(36)}-${rand}`;
}

/**
 * Parse a free-text block (one source per line) into `SourceItemInput[]`.
 * A bare line becomes the narration `body`; a `title | body` line splits on the
 * first pipe. Blank lines are dropped.
 */
export function parseSourceLines(text: string): SourceItemInput[] {
  return (text ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => {
      const pipe = line.indexOf("|");
      if (pipe === -1) return { body: line };
      const title = line.slice(0, pipe).trim();
      const body = line.slice(pipe + 1).trim();
      return title ? { title, body } : { body };
    })
    .filter((item) => (item.body ?? "").length > 0);
}

/**
 * Parse a comma/newline-separated list (accounts, hooks) into a trimmed,
 * de-duplicated, non-empty string array.
 */
export function parseCsvList(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of (text ?? "").split(/[\n,]/)) {
    const value = raw.trim();
    if (value.length > 0 && !seen.has(value)) {
      seen.add(value);
      out.push(value);
    }
  }
  return out;
}

/**
 * Build the `POST /run` request body from raw console fields. Empty collections
 * are omitted so the backend applies its config defaults; `null` numeric
 * overrides mean "unset".
 */
export function buildRunInput(fields: {
  sourceText: string;
  hooksText?: string;
  accountsText?: string;
  platforms?: string[];
  subject?: string;
  templateSlug?: string;
  maxPerAccount?: number | null;
}): RunChannelInput {
  const input: RunChannelInput = {
    source_items: parseSourceLines(fields.sourceText),
  };
  const hooks = parseCsvList(fields.hooksText ?? "");
  if (hooks.length > 0) input.hooks = hooks;
  const accounts = parseCsvList(fields.accountsText ?? "");
  if (accounts.length > 0) input.accounts = accounts;
  if (fields.platforms && fields.platforms.length > 0) {
    input.platforms = [...fields.platforms];
  }
  const subject = (fields.subject ?? "").trim();
  if (subject) input.subject = subject;
  const slug = (fields.templateSlug ?? "").trim();
  if (slug) input.template_slug = slug;
  if (typeof fields.maxPerAccount === "number" && fields.maxPerAccount >= 0) {
    input.max_per_account = Math.trunc(fields.maxPerAccount);
  }
  return input;
}

/** Whether a run request has at least one source item to render. */
export function canTriggerRun(input: RunChannelInput): boolean {
  return (input.source_items?.length ?? 0) > 0;
}

/** Total non-failed clips rendered today across every account. */
export function totalRenderedToday(
  renderedToday: Record<string, number>,
): number {
  return Object.values(renderedToday ?? {}).reduce(
    (sum, n) => sum + (Number.isFinite(n) ? n : 0),
    0,
  );
}

/** One-line human summary of a render pass outcome. */
export function formatRunSummary(summary: RunSummary): string {
  return (
    `${summary.rendered} rendered · ${summary.paced_out} paced out · ` +
    `${summary.skipped_duplicates} dupes · ${summary.enqueue_failures} failed`
  );
}

/** One-line human summary of a publish-pacing pass outcome. */
export function formatScheduleSummary(summary: ScheduleSummary): string {
  return `${summary.scheduled} scheduled of ${summary.considered} considered`;
}

/** Extract the stored outcome summary from a persisted run row (may be absent). */
export function runOutcome(run: ChannelRunView): RunSummary | null {
  const summary = run.params?.summary;
  if (!summary || typeof summary !== "object") return null;
  return summary;
}
