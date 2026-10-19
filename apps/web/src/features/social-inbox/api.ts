/** Social inbox API — wraps /social-inbox/*. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import type {
  InboxOverview,
  InboxPlatform,
  InboxThreadDetail,
  ReplySuggestions,
  ThreadFilters,
  ThreadPage,
  ThreadStatus,
} from "./types";

const PAGE_SIZE = 30;

const threadPath = (threadId: string) =>
  `/social-inbox/threads/${encodeURIComponent(threadId)}`;

/** Platforms (what each allows), tracked posts with engagement counts, totals. */
export function getInboxOverview(options?: RequestOptions): Promise<InboxOverview> {
  return apiRequest<InboxOverview>("/social-inbox", { options });
}

/** Pull new comments and messages now (rate limited server-side). */
export function syncInbox(options?: RequestOptions): Promise<InboxOverview> {
  return apiRequest<InboxOverview>("/social-inbox/sync", { method: "POST", options });
}

export function listThreads(
  filters: ThreadFilters,
  offset = 0,
  options?: RequestOptions,
): Promise<ThreadPage> {
  const params = new URLSearchParams();
  if (filters.platform) params.set("platform", filters.platform);
  if (filters.postId) params.set("post_id", filters.postId);
  params.set("status", filters.status);
  if (filters.kind) params.set("kind", filters.kind);
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String(offset));
  return apiRequest<ThreadPage>(`/social-inbox/threads?${params.toString()}`, { options });
}

export function getThread(threadId: string, options?: RequestOptions): Promise<InboxThreadDetail> {
  return apiRequest<InboxThreadDetail>(threadPath(threadId), { options });
}

export function suggestReplies(
  threadId: string,
  options?: RequestOptions,
): Promise<ReplySuggestions> {
  return apiRequest<ReplySuggestions>(`${threadPath(threadId)}/suggestions`, {
    method: "POST",
    options,
  });
}

export function sendReply(
  threadId: string,
  text: string,
  options?: RequestOptions,
): Promise<InboxThreadDetail> {
  return apiRequest<InboxThreadDetail>(`${threadPath(threadId)}/reply`, {
    method: "POST",
    body: { text },
    options,
  });
}

export function setThreadStatus(
  threadId: string,
  status: ThreadStatus,
  replyText = "",
  options?: RequestOptions,
): Promise<InboxThreadDetail> {
  return apiRequest<InboxThreadDetail>(`${threadPath(threadId)}/status`, {
    method: "POST",
    body: { status, reply_text: replyText },
    options,
  });
}

interface AuthorizeInfo {
  authorize_url: string;
  state: string;
}

/** Start an OAuth reconnect that asks for inbox scopes (comments / messages). */
export function authorizeInboxScopes(
  platform: InboxPlatform,
  scopes: string,
  options?: RequestOptions,
): Promise<AuthorizeInfo> {
  const query = scopes ? `?scopes=${encodeURIComponent(scopes)}` : "";
  return apiRequest<AuthorizeInfo>(
    `/connections/${encodeURIComponent(platform)}/authorize${query}`,
    { options },
  );
}

export { PAGE_SIZE };
