/**
 * Approvals feed client. Mirrors the wire shape of `GET /api/v1/approvals`
 * (apps/api/app/domains/approvals/service.py `item_view`), which Rally also reads.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type ApprovalSource =
  | "social_reply"
  | "publish_hold"
  | "ad_budget"
  | "design_publish"
  | "capture_publish"
  | "catalog_import";

export type ApprovalStatus = "pending" | "approved" | "executed" | "rejected" | "edited" | "expired" | "failed";
export type StatusFilter = "pending" | "all";

export interface ApprovalItem {
  id: string;
  source: ApprovalSource;
  external_ref: string;
  title: string;
  summary: string;
  risk: "low" | "medium" | "high";
  payload: Record<string, unknown> & { editable_fields?: string[]; open_path?: string; text?: string };
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

export const SOURCE_LABELS: Record<ApprovalSource, string> = {
  social_reply: "Reply draft",
  publish_hold: "Held post",
  ad_budget: "Ad budget",
  design_publish: "Design post",
  capture_publish: "Capture post",
  catalog_import: "Catalog import",
};

export function listApprovals(
  params: { status: StatusFilter; source: ApprovalSource | ""; offset: number; limit: number },
  options: RequestOptions,
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
  decision: "approve" | "reject",
  body: { note?: string; edits?: Record<string, string> },
  options: RequestOptions,
): Promise<DecisionOutcome> {
  return apiRequest<DecisionOutcome>(`/approvals/${encodeURIComponent(id)}/${decision}`, {
    method: "POST",
    body: { via: "web", note: body.note ?? "", ...(body.edits ? { edits: body.edits } : {}) },
    options,
  });
}

/** Scanned sources that only add items after the owner opts in (default off). */
export type AutoSource = "capture_publish" | "catalog_import";

export interface ApprovalFeedSettings {
  auto_sources: Record<AutoSource, boolean>;
  labels: Record<AutoSource, string>;
  stored: boolean;
}

export function getApprovalSettings(options: RequestOptions): Promise<ApprovalFeedSettings> {
  return apiRequest<ApprovalFeedSettings>("/approvals/settings", { options });
}

export function updateApprovalSettings(
  autoSources: Partial<Record<AutoSource, boolean>>,
  options: RequestOptions,
): Promise<ApprovalFeedSettings> {
  return apiRequest<ApprovalFeedSettings>("/approvals/settings", {
    method: "PUT",
    body: { auto_sources: autoSources },
    options,
  });
}
