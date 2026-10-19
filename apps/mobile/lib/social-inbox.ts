/**
 * Social inbox client — Expo. Mirrors the web's `src/features/social-inbox/api.ts`
 * over the same backend (`apps/api/app/domains/social_inbox`):
 *
 *   GET  /social-inbox                          platforms (what each allows), posts, totals
 *   POST /social-inbox/sync                     pull new comments and messages now
 *   GET  /social-inbox/threads?…                one page of threads
 *   GET  /social-inbox/threads/{id}             one thread with its messages
 *   POST /social-inbox/threads/{id}/suggestions reply suggestions
 *   POST /social-inbox/threads/{id}/reply       send a reply through the platform API
 *   POST /social-inbox/threads/{id}/status      mark replied / done / needs reply
 *
 * Replying is capability-driven: each thread carries `reply.mode` ("api" when
 * the platform lets Menivor post the reply, "manual" when the creator must
 * answer on the platform itself). The pure helpers below turn that into the
 * screen's affordances so the rules are unit-tested.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export type InboxPlatform =
  | "youtube"
  | "instagram"
  | "tiktok"
  | "facebook"
  | "threads"
  | "bluesky"
  | "linkedin"
  | "x"
  | "pinterest"
  | "telegram"
  | "discord"
  | "mastodon";
export type AccessLevel = "yes" | "needs_permission" | "not_offered";
export type ThreadStatus = "needs_reply" | "replied" | "done";
export type ThreadKind = "comment" | "dm";

export interface Access {
  read: AccessLevel;
  reply: AccessLevel;
  note: string;
}

export interface PlatformCapability {
  platform: InboxPlatform;
  label: string;
  connected: boolean;
  comments: Access;
  dms: Access;
  needs_reconnect: boolean;
  reconnect_scopes: string;
}

export interface InboxOverview {
  platforms: PlatformCapability[];
  totals: {
    by_status: Partial<Record<ThreadStatus, number>>;
    needs_reply_by_platform: Partial<Record<InboxPlatform, number>>;
  };
  sending_enabled: boolean;
  last_synced_at: string | null;
  sync?: { discovered: number; synced: number };
}

export interface ReplyMode {
  mode: "api" | "manual";
  reason: string;
  open_url: string;
}

export interface InboxMessage {
  id: string;
  author: string;
  text: string;
  at: string | null;
  from_me: boolean;
  via: string;
}

export interface InboxThread {
  id: string;
  platform: InboxPlatform;
  platform_label: string;
  kind: ThreadKind;
  post_id: string | null;
  post_title: string;
  author_name: string;
  text: string;
  like_count: number;
  message_count: number;
  status: ThreadStatus;
  last_message_at: string | null;
  replied_at: string | null;
  reply_via: string;
  reply_text: string;
  reply: ReplyMode;
}

export interface InboxThreadDetail extends InboxThread {
  messages: InboxMessage[];
}

export interface ThreadPage {
  threads: InboxThread[];
  total: number;
  limit: number;
  offset: number;
}

export interface ThreadFilters {
  platform: "" | InboxPlatform;
  status: ThreadStatus | "all";
  kind: "" | ThreadKind;
}

export interface ReplySuggestions {
  suggestions: string[];
  source: "ai" | "template";
  intent: string;
}

export const INBOX_PAGE_SIZE = 30;
/** Platform replies are short; the API rejects anything longer than this. */
export const MAX_REPLY_CHARS = 1000;

export const DEFAULT_FILTERS: ThreadFilters = Object.freeze({
  platform: "",
  status: "needs_reply",
  kind: "",
});

const threadPath = (threadId: string) =>
  `/social-inbox/threads/${encodeURIComponent(threadId)}`;

export function getInboxOverview(options?: RequestOptions): Promise<InboxOverview> {
  return request<InboxOverview>("/social-inbox", { options });
}

export function syncInbox(options?: RequestOptions): Promise<InboxOverview> {
  return request<InboxOverview>("/social-inbox/sync", { method: "POST", options });
}

/** Query string for one page of threads (kept pure so it is testable). */
export function threadQuery(filters: ThreadFilters, offset = 0): string {
  const params = new URLSearchParams();
  if (filters.platform) params.set("platform", filters.platform);
  params.set("status", filters.status);
  if (filters.kind) params.set("kind", filters.kind);
  params.set("limit", String(INBOX_PAGE_SIZE));
  params.set("offset", String(Math.max(0, Math.trunc(offset) || 0)));
  return params.toString();
}

export function listThreads(
  filters: ThreadFilters,
  offset = 0,
  options?: RequestOptions,
): Promise<ThreadPage> {
  return request<ThreadPage>(`/social-inbox/threads?${threadQuery(filters, offset)}`, {
    options,
  });
}

export function getThread(threadId: string, options?: RequestOptions): Promise<InboxThreadDetail> {
  return request<InboxThreadDetail>(threadPath(threadId), { options });
}

export function suggestReplies(
  threadId: string,
  options?: RequestOptions,
): Promise<ReplySuggestions> {
  return request<ReplySuggestions>(`${threadPath(threadId)}/suggestions`, {
    method: "POST",
    options,
  });
}

export function sendReply(
  threadId: string,
  text: string,
  options?: RequestOptions,
): Promise<InboxThreadDetail> {
  return request<InboxThreadDetail>(`${threadPath(threadId)}/reply`, {
    method: "POST",
    body: { text: text.trim() },
    options,
  });
}

export function setThreadStatus(
  threadId: string,
  status: ThreadStatus,
  replyText = "",
  options?: RequestOptions,
): Promise<InboxThreadDetail> {
  return request<InboxThreadDetail>(`${threadPath(threadId)}/status`, {
    method: "POST",
    body: { status, reply_text: replyText.trim() },
    options,
  });
}

// --------------------------------------------------------------------------- //
// Pure helpers
// --------------------------------------------------------------------------- //

export const STATUS_LABEL: Readonly<Record<ThreadStatus, string>> = Object.freeze({
  needs_reply: "Needs reply",
  replied: "Replied",
  done: "Done",
});

export interface ReplyAffordance {
  /** Menivor can post the reply through the platform API. */
  canSendInApp: boolean;
  /** Link to answer on the platform itself ("" when there is none). */
  openUrl: string;
  /** Honest one-line reason shown under the composer. */
  note: string;
}

/**
 * What the thread screen may offer. In-app sending needs both the thread's
 * reply mode to be "api" and the deployment to have sending turned on.
 */
export function replyAffordance(
  thread: Pick<InboxThread, "reply" | "platform_label">,
  sendingEnabled: boolean,
): ReplyAffordance {
  const openUrl = (thread.reply?.open_url || "").trim();
  const reason = (thread.reply?.reason || "").trim();
  if (thread.reply?.mode === "api" && sendingEnabled) {
    return { canSendInApp: true, openUrl, note: reason };
  }
  if (thread.reply?.mode === "api" && !sendingEnabled) {
    return {
      canSendInApp: false,
      openUrl,
      note: "Sending replies from Menivor is turned off on this server. Reply on the platform, then mark it replied here.",
    };
  }
  return {
    canSendInApp: false,
    openUrl,
    note:
      reason ||
      `${thread.platform_label || "This platform"} does not let apps post replies. Reply there, then mark it replied here.`,
  };
}

/** Trimmed reply text or an error message when it cannot be sent. */
export function validateReply(text: string): { ok: true; text: string } | { ok: false; error: string } {
  const trimmed = text.trim();
  if (!trimmed) return { ok: false, error: "Write a reply first." };
  if (trimmed.length > MAX_REPLY_CHARS) {
    return { ok: false, error: `Replies can be at most ${MAX_REPLY_CHARS} characters.` };
  }
  return { ok: true, text: trimmed };
}

/** Platforms the caller can actually read something from (for the filter chips). */
export function readablePlatforms(platforms: readonly PlatformCapability[]): PlatformCapability[] {
  return platforms.filter(
    (p) => p.connected && (p.comments.read === "yes" || p.dms.read === "yes"),
  );
}

/** Merge a fresh page into the list, de-duplicating by id (new array). */
export function mergeThreads(
  current: readonly InboxThread[],
  page: readonly InboxThread[],
): InboxThread[] {
  const seen = new Set(current.map((t) => t.id));
  return [...current, ...page.filter((t) => !seen.has(t.id))];
}

/** Replace one thread in a list with its updated copy (new array). */
export function replaceThread(
  list: readonly InboxThread[],
  updated: InboxThread,
  filters: ThreadFilters,
): InboxThread[] {
  const stillMatches = filters.status === "all" || filters.status === updated.status;
  if (!stillMatches) return list.filter((t) => t.id !== updated.id);
  return list.map((t) => (t.id === updated.id ? { ...t, ...updated } : t));
}

export function relativeTime(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const seconds = Math.max(0, Math.round((now.getTime() - at.getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return at.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * API errors arrive as "<request id>: <message>". Keep only the readable part
 * so the request id never leaks into the UI.
 */
export function readableApiMessage(message: string, fallback: string): string {
  const text = (message || "").trim();
  if (!text) return fallback;
  const stripped = text.replace(/^(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{16,}:\s*/, "").trim();
  if (!stripped) return fallback;
  return stripped.charAt(0).toUpperCase() + stripped.slice(1);
}
