/**
 * Approvals feed client for Expo. Mirrors the web client
 * (apps/web/app/approvals/_components/api.ts) and the wire shape of
 * `GET /api/v1/approvals` (apps/api/app/domains/approvals/service.py
 * `item_view`). Decisions are recorded with `via: "mobile"`.
 *
 * The pure helpers at the bottom (decision body, list reducer, approve gate)
 * carry the screen's behaviour and are unit-tested under node.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api/client";

export type ApprovalSource =
  | "social_reply"
  | "publish_hold"
  | "ad_budget"
  | "design_publish"
  | "capture_publish"
  | "catalog_import";

export type ApprovalStatus =
  | "pending"
  | "approved"
  | "executed"
  | "rejected"
  | "edited"
  | "expired"
  | "failed";

export type StatusFilter = "pending" | "all";
export type Decision = "approve" | "reject";

export interface ApprovalItem {
  id: string;
  source: ApprovalSource;
  external_ref: string;
  title: string;
  summary: string;
  risk: "low" | "medium" | "high";
  payload: Record<string, unknown> & {
    editable_fields?: string[];
    open_path?: string;
    text?: string;
  };
  edited_payload: Record<string, unknown> | null;
  status: ApprovalStatus;
  decided_by: string | null;
  decided_via: string;
  decided_at: string | null;
  decision_note: string;
  result: Record<string, unknown>;
  error: string;
  expires_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  open_url: string | null;
  can_decide: boolean;
}

export interface ApprovalList {
  items: ApprovalItem[];
  total: number;
  limit: number;
  offset: number;
  pending_count: number;
  pending_by_source: Partial<Record<ApprovalSource, number>>;
  unavailable_sources: string[];
}

export interface DecisionOutcome {
  item: ApprovalItem;
  idempotent: boolean;
}

/** Scanned sources that only add items after the owner opts in (default off). */
export type AutoSource = "capture_publish" | "catalog_import";

export interface ApprovalFeedSettings {
  auto_sources: Record<AutoSource, boolean>;
  labels: Record<AutoSource, string>;
  stored: boolean;
}

export const SOURCE_LABELS: Record<ApprovalSource, string> = {
  social_reply: "Reply draft",
  publish_hold: "Held post",
  ad_budget: "Ad budget",
  design_publish: "Design post",
  capture_publish: "Capture post",
  catalog_import: "Catalog import",
};

export const APPROVAL_SOURCES = Object.keys(SOURCE_LABELS) as ApprovalSource[];

/** Sources whose approval schedules real posts, so they follow the publishing launch gate. */
export const PUBLISHING_SOURCES: ReadonlySet<ApprovalSource> = new Set<ApprovalSource>([
  "publish_hold",
  "design_publish",
]);

/** Server-side cap on `note` (DecisionBody.note max_length). */
export const NOTE_MAX = 1000;
/** Server-side cap on edited text for reply drafts. */
export const TEXT_MAX = 2000;

export function listApprovals(
  params: { status: StatusFilter; source: ApprovalSource | ""; offset: number; limit: number },
  options?: RequestOptions,
): Promise<ApprovalList> {
  const query = new URLSearchParams({
    status: params.status,
    limit: String(params.limit),
    offset: String(params.offset),
  });
  if (params.source) query.set("source", params.source);
  return apiRequest<ApprovalList>(`/approvals?${query.toString()}`, { options });
}

export function decideApproval(
  id: string,
  decision: Decision,
  body: DecisionBody,
  options?: RequestOptions,
): Promise<DecisionOutcome> {
  return apiRequest<DecisionOutcome>(
    `/approvals/${encodeURIComponent(id)}/${decision}`,
    { method: "POST", body, options },
  );
}

export function getApprovalSettings(options?: RequestOptions): Promise<ApprovalFeedSettings> {
  return apiRequest<ApprovalFeedSettings>("/approvals/settings", { options });
}

export function updateApprovalSettings(
  autoSources: Partial<Record<AutoSource, boolean>>,
  options?: RequestOptions,
): Promise<ApprovalFeedSettings> {
  return apiRequest<ApprovalFeedSettings>("/approvals/settings", {
    method: "PUT",
    body: { auto_sources: autoSources },
    options,
  });
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export interface DecisionBody {
  via: "mobile";
  note: string;
  edits?: { text: string };
}

/** The item's original draft text, or "" when it has none. */
export function originalText(item: ApprovalItem): string {
  return typeof item.payload.text === "string" ? item.payload.text : "";
}

/** True when the owner may edit the draft text before approving. */
export function canEditText(item: ApprovalItem): boolean {
  return item.can_decide && (item.payload.editable_fields ?? []).includes("text");
}

/**
 * Body for POST /approvals/{id}/{decision}. The note (comment) is trimmed and
 * capped; edited text is only sent on approve, only when editable, and only
 * when it actually differs from the original draft.
 */
export function buildDecisionBody(
  item: ApprovalItem,
  decision: Decision,
  note: string,
  editedText: string | null,
): DecisionBody {
  const body: DecisionBody = { via: "mobile", note: note.trim().slice(0, NOTE_MAX) };
  if (
    decision === "approve" &&
    editedText !== null &&
    canEditText(item) &&
    editedText.trim() !== originalText(item).trim() &&
    editedText.trim().length > 0
  ) {
    return { ...body, edits: { text: editedText.slice(0, TEXT_MAX) } };
  }
  return body;
}

/** Approve is blocked for post-scheduling items while publishing is closed. */
export function approveBlocked(item: ApprovalItem, publishingOpen: boolean): boolean {
  return PUBLISHING_SOURCES.has(item.source) && !publishingOpen;
}

/**
 * Apply a decided item to the loaded page: drop it from the pending view,
 * replace it in history, and keep the pending counters honest.
 */
export function applyDecision(
  list: ApprovalList,
  next: ApprovalItem,
  filter: StatusFilter,
): ApprovalList {
  const previous = list.items.find((item) => item.id === next.id);
  const leftPending = !!previous && previous.can_decide && !next.can_decide;
  const items =
    filter === "pending"
      ? list.items.filter((item) => item.id !== next.id)
      : list.items.map((item) => (item.id === next.id ? next : item));
  const sourceCount = list.pending_by_source[next.source] ?? 0;
  return {
    ...list,
    items,
    total: filter === "pending" && previous ? Math.max(0, list.total - 1) : list.total,
    pending_count: Math.max(0, list.pending_count - (leftPending ? 1 : 0)),
    pending_by_source: leftPending
      ? { ...list.pending_by_source, [next.source]: Math.max(0, sourceCount - 1) }
      : list.pending_by_source,
  };
}

function asRecordList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((row): row is Record<string, unknown> => typeof row === "object" && row !== null)
    : [];
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string" && v.length > 0)
    : [];
}

function platformName(platform: string): string {
  const text = platform.replace(/_/g, " ");
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

/** What approving an item did, as readable lines (from `item.result`). */
export interface ResultSummary {
  posts: string[];
  skipped: string[];
  jobIds: string[];
  jobsLabel: string;
  note: string;
}

/**
 * Summarise `item.result` (written by the approvals adapters): queued posts,
 * platforms skipped with their reason, reel jobs and a free-form note. Returns
 * null when there is nothing worth showing.
 */
export function summarizeResult(result: Record<string, unknown>): ResultSummary | null {
  const posts = asRecordList(result.posts)
    .filter((r) => typeof r.id === "string" && typeof r.platform === "string")
    .map((r) => {
      const label = typeof r.channel_label === "string" && r.channel_label ? ` (${r.channel_label})` : "";
      const status = typeof r.status === "string" ? r.status : "queued";
      const when = formatWhen(typeof r.scheduled_at === "string" ? r.scheduled_at : null);
      return `${platformName(String(r.platform))}${label}: ${status}${when ? `, ${when}` : ""}`;
    });
  const skipped = asRecordList(result.skipped)
    .filter((r) => typeof r.platform === "string")
    .map((r) => {
      const message = typeof r.message === "string" && r.message ? `: ${r.message}` : "";
      return `${platformName(String(r.platform))}${message}`;
    });
  const jobIds = asStringList(result.job_ids);
  const credits = typeof result.credits === "number" ? result.credits : null;
  const replayed = result.replayed === true;
  const jobsLabel = replayed
    ? "Reel jobs (already created earlier; not charged again)"
    : credits !== null
      ? `Reel jobs (${credits} credit${credits === 1 ? "" : "s"})`
      : "Reel jobs";
  const note = typeof result.note === "string" ? result.note : "";
  if (!posts.length && !skipped.length && !jobIds.length && !note) return null;
  return { posts, skipped, jobIds, jobsLabel, note };
}
