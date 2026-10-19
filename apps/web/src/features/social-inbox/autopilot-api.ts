/**
 * Engagement autopilot API - wraps /social-inbox/autopilot/* and /social-inbox/leads.
 * Mirrors apps/api/app/domains/social_inbox/autopilot.py.
 */

import { ApiError, apiRequest, type RequestOptions } from "@/src/shared/api";
import type { InboxPlatform } from "./types";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type ReplyModeSetting = "off" | "approve" | "auto";
export type ActionKind = "like" | "reply" | "hide" | "flag" | "lead" | "settings";
export type ActionStatus = "pending_approval" | "queued" | "done" | "rejected" | "skipped" | "failed";
export type LeadStatus = "new" | "contacted" | "won" | "dismissed";

export interface AutopilotSupport {
  read: string;
  like: boolean;
  like_note: string;
  hide: boolean;
  hide_note: string;
  reply: string;
  reply_note: string;
}

export interface AutopilotRules {
  enabled: boolean;
  auto_like: boolean;
  reply_mode: ReplyModeSetting;
  reply_to_questions: boolean;
  hide_spam: boolean;
  hide_abuse: boolean;
  route_leads: boolean;
  daily_cap: number;
  blocked_words: string[];
}

export interface AutopilotPlatform extends AutopilotRules {
  platform: InboxPlatform;
  label: string;
  connected: boolean;
  support: AutopilotSupport;
  used_today: number;
  last_run_at: string | null;
}

export interface AutopilotOverview {
  platforms: AutopilotPlatform[];
  pending_approvals: number;
  new_leads: number;
  sending_enabled: boolean;
  max_daily_cap: number;
}

export interface EngagementAction {
  id: string;
  thread_id: string | null;
  platform: InboxPlatform;
  platform_label: string;
  kind: ActionKind;
  status: ActionStatus;
  actor: "autopilot" | "creator";
  label: string;
  confidence: number | null;
  signals: string[];
  reason: string;
  text: string;
  text_source: string;
  excerpt: string;
  author_name: string;
  error: string;
  created_at: string | null;
  executed_at: string | null;
  decided_at: string | null;
}

export interface ActionPage {
  actions: EngagementAction[];
  total: number;
  limit: number;
  offset: number;
}

export interface Lead {
  id: string;
  thread_id: string | null;
  platform: InboxPlatform;
  platform_label: string;
  source: "dm" | "comment";
  author_name: string;
  excerpt: string;
  signals: string[];
  score: number;
  status: LeadStatus;
  note: string;
  permalink: string;
  last_message_at: string | null;
  created_at: string | null;
}

export interface LeadPage {
  leads: Lead[];
  total: number;
  limit: number;
  offset: number;
}

export interface RunSummary {
  checked: number;
  liked: number;
  hidden: number;
  flagged: number;
  leads: number;
  replies_sent: number;
  drafts: number;
  skipped: number;
  failed: number;
}

export function getAutopilot(options?: RequestOptions): Promise<AutopilotOverview> {
  return apiRequest<AutopilotOverview>("/social-inbox/autopilot", { options });
}

export function updateAutopilot(
  platform: InboxPlatform,
  changes: Partial<AutopilotRules>,
  options?: RequestOptions,
): Promise<AutopilotPlatform> {
  return apiRequest<AutopilotPlatform>(`/social-inbox/autopilot/${platform}`, {
    method: "PUT",
    body: changes,
    options,
  });
}

export function runAutopilot(options?: RequestOptions): Promise<RunSummary> {
  return apiRequest<RunSummary>("/social-inbox/autopilot/run", { method: "POST", options });
}

export function listApprovals(offset = 0, options?: RequestOptions): Promise<ActionPage> {
  return apiRequest<ActionPage>(`/social-inbox/autopilot/approvals?limit=50&offset=${offset}`, { options });
}

export function approveDraft(actionId: string, text: string, options?: RequestOptions): Promise<EngagementAction> {
  return apiRequest<EngagementAction>(
    `/social-inbox/autopilot/approvals/${encodeURIComponent(actionId)}/approve`,
    { method: "POST", body: { text }, options },
  );
}

export function rejectDraft(actionId: string, options?: RequestOptions): Promise<EngagementAction> {
  return apiRequest<EngagementAction>(
    `/social-inbox/autopilot/approvals/${encodeURIComponent(actionId)}/reject`,
    { method: "POST", options },
  );
}

export function listActivity(
  filters: { kind?: string; status?: string; platform?: string },
  offset = 0,
  options?: RequestOptions,
): Promise<ActionPage> {
  const params = new URLSearchParams();
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.status) params.set("status", filters.status);
  if (filters.platform) params.set("platform", filters.platform);
  params.set("limit", "50");
  params.set("offset", String(offset));
  return apiRequest<ActionPage>(`/social-inbox/autopilot/activity?${params.toString()}`, { options });
}

export function listLeads(status: LeadStatus | "", offset = 0, options?: RequestOptions): Promise<LeadPage> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("limit", "50");
  params.set("offset", String(offset));
  return apiRequest<LeadPage>(`/social-inbox/leads?${params.toString()}`, { options });
}

export function updateLead(
  leadId: string,
  changes: { status?: LeadStatus; note?: string },
  options?: RequestOptions,
): Promise<Lead> {
  return apiRequest<Lead>(`/social-inbox/leads/${encodeURIComponent(leadId)}`, {
    method: "POST",
    body: changes,
    options,
  });
}

/** API messages carry a request id prefix; strip it for display. */
export function cleanError(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/** When a reply can't be sent from Menivor, the API returns where to answer instead. */
export function openUrlOf(err: unknown): string {
  if (!(err instanceof ApiError)) return "";
  const detail = err.detail as { data?: { open_url?: string } } | undefined;
  return typeof detail?.data?.open_url === "string" ? detail.data.open_url : "";
}

export const ACTION_LABELS: Record<ActionKind, string> = {
  like: "Liked",
  reply: "Reply",
  hide: "Hidden",
  flag: "Flagged",
  lead: "Sent to Leads",
  settings: "Rules changed",
};

export const ACTION_STATUS_LABELS: Record<ActionStatus, string> = {
  pending_approval: "Waiting for approval",
  queued: "In progress",
  done: "Done",
  rejected: "Discarded",
  skipped: "Skipped",
  failed: "Failed",
};

export const LEAD_STATUS_LABELS: Record<LeadStatus, string> = {
  new: "New",
  contacted: "Contacted",
  won: "Won",
  dismissed: "Dismissed",
};
