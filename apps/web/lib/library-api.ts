/**
 * Library-management client: reel lifecycle (rename / archive / delete /
 * cancel), paged reel history, the caller's uploaded assets, and pending team
 * invites with shareable accept links. Re-exported from `@/lib/api` so every
 * feature keeps a single import surface.
 *
 * Response shapes are normalized defensively (bare arrays or `{ items }`-style
 * wrappers) because the backend envelope `data` varies between domains.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";
import type {
  AssignableWorkspaceRole,
  Job,
  Member,
  WorkspaceRole,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
}

function num(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/** Pull the first array found under `keys` (or the value itself when it is one). */
function pickArray(data: unknown, keys: readonly string[]): unknown[] {
  if (Array.isArray(data)) return data;
  if (!isObject(data)) return [];
  for (const key of keys) {
    const value = data[key];
    if (Array.isArray(value)) return value;
  }
  return [];
}

function queryString(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

// ---------------------------------------------------------------------------
// Reels: paged history + lifecycle
// ---------------------------------------------------------------------------

/** Largest page the backend serves for GET /jobs. */
export const JOBS_PAGE_MAX = 100;

export interface JobsPage {
  jobs: Job[];
  /** True when the server likely has more rows past this page. */
  hasMore: boolean;
  /** Offset to request for the next page. */
  nextOffset: number;
}

export interface ListJobsPageParams {
  limit?: number;
  offset?: number;
  /** Ask the server to include archived reels (filtered client-side). */
  includeArchived?: boolean;
}

/**
 * GET /jobs?limit&offset — one page of the caller's reels, newest first.
 * `hasMore` is inferred from a full page (the endpoint returns no total), or
 * taken from an explicit `has_more` / `total` when the backend provides one.
 */
export async function listJobsPage(
  params: ListJobsPageParams = {},
  options?: RequestOptions,
): Promise<JobsPage> {
  const limit = Math.max(1, Math.min(JOBS_PAGE_MAX, params.limit ?? JOBS_PAGE_MAX));
  const offset = Math.max(0, params.offset ?? 0);
  const data = await request<unknown>(
    `/jobs${queryString({
      limit,
      offset,
      include_archived: params.includeArchived ? "true" : undefined,
    })}`,
    { options },
  );
  const jobs = pickArray(data, ["jobs", "items"]) as Job[];
  const explicitMore = isObject(data) && typeof data.has_more === "boolean" ? data.has_more : undefined;
  const total = isObject(data) ? num(data.total) : undefined;
  const hasMore =
    explicitMore ?? (total !== undefined ? offset + jobs.length < total : jobs.length >= limit);
  return { jobs, hasMore, nextOffset: offset + jobs.length };
}

/** Editable reel metadata for PATCH /jobs/{id}. */
export interface JobUpdateRequest {
  title?: string | null;
  archived?: boolean;
}

/** PATCH /jobs/{id} — rename and/or archive/unarchive a reel. Returns the updated job. */
export function updateJob(
  id: string,
  body: JobUpdateRequest,
  options?: RequestOptions,
): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body,
    options,
  });
}

export interface JobDeleteResult {
  job_id: string;
  deleted: boolean;
}

/** DELETE /jobs/{id} — permanently remove a terminal reel from the library. */
export async function deleteJob(
  id: string,
  options?: RequestOptions,
): Promise<JobDeleteResult> {
  const data = await request<unknown>(`/jobs/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
  const deleted = isObject(data) && typeof data.deleted === "boolean" ? data.deleted : true;
  return { job_id: id, deleted };
}

/**
 * POST /jobs/{id}/cancel — stop an in-flight reel. The server releases the
 * unspent credit hold through the ledger and returns the (now failed/cancelled)
 * job; `refunded_credits` reports what went back to the payer when present.
 */
export async function cancelJob(id: string, options?: RequestOptions): Promise<Job> {
  const data = await request<unknown>(`/jobs/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
    options,
  });
  if (isObject(data) && isObject(data.job)) {
    const refunded = num(data.refunded_credits);
    return {
      ...(data.job as unknown as Job),
      cancelled: true,
      ...(refunded !== undefined ? { refunded_credits: refunded } : {}),
    };
  }
  return { ...(data as Job), cancelled: true };
}

/** Human title for a reel: its rename, else its hook, else a short id. */
export function jobDisplayTitle(job: Pick<Job, "job_id" | "title" | "hook">): string {
  const title = job.title?.trim();
  if (title) return title;
  const hook = job.hook?.trim();
  if (hook) return hook;
  return `Reel ${job.job_id.slice(0, 8)}`;
}

// ---------------------------------------------------------------------------
// Uploads library (GET /uploads, DELETE /uploads/{asset_id})
// ---------------------------------------------------------------------------

export type UploadKind = "image" | "video" | "audio" | "upload";

export const UPLOAD_KINDS: readonly UploadKind[] = ["video", "image", "audio", "upload"];

/** One caller-owned uploaded asset. */
export interface UploadAsset {
  asset_id: string;
  key: string;
  kind: UploadKind;
  /** Presigned GET URL for preview, when the backend could sign it. */
  get_url?: string;
  /** Presigned URL that downloads under the original filename. */
  download_url?: string;
  content_type?: string;
  size?: number;
  filename?: string;
  created_at?: string;
}

function normalizeKind(value: unknown, contentType?: string): UploadKind {
  const kind = (str(value) ?? "").toLowerCase();
  if (kind === "image" || kind === "video" || kind === "audio") return kind;
  const type = (contentType ?? "").toLowerCase();
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("video/")) return "video";
  if (type.startsWith("audio/")) return "audio";
  return "upload";
}

function normalizeUpload(raw: unknown): UploadAsset | null {
  if (!isObject(raw)) return null;
  const assetId = str(raw.asset_id) ?? str(raw.id);
  const key = str(raw.key) ?? str(raw.r2_key) ?? "";
  if (!assetId) return null;
  const contentType = str(raw.content_type) ?? str(raw.mime_type);
  const filename = str(raw.filename) ?? str(raw.name) ?? (key ? key.split("/").pop() : undefined);
  return {
    asset_id: assetId,
    key,
    kind: normalizeKind(raw.kind, contentType),
    get_url: str(raw.get_url) ?? str(raw.url) ?? str(raw.download_url),
    download_url: str(raw.download_url) ?? str(raw.get_url) ?? str(raw.url),
    content_type: contentType,
    size: num(raw.size) ?? num(raw.size_bytes) ?? num(raw.bytes),
    filename,
    created_at: str(raw.created_at),
  };
}

export interface UploadsPage {
  uploads: UploadAsset[];
  hasMore: boolean;
  nextOffset: number;
}

/**
 * GET /uploads — the caller's registered uploads, newest first, with
 * short-lived signed preview/download URLs (null when storage is offline).
 */
export async function listUploads(
  params: { kind?: UploadKind; limit?: number; offset?: number } = {},
  options?: RequestOptions,
): Promise<UploadsPage> {
  const limit = Math.max(1, Math.min(100, params.limit ?? 60));
  const offset = Math.max(0, params.offset ?? 0);
  const data = await request<unknown>(
    `/uploads${queryString({ kind: params.kind, limit, offset })}`,
    { options },
  );
  const rows = pickArray(data, ["uploads", "assets", "items"]);
  const uploads = rows
    .map(normalizeUpload)
    .filter((u): u is UploadAsset => u !== null);
  const explicitMore = isObject(data) && typeof data.has_more === "boolean" ? data.has_more : undefined;
  return {
    uploads,
    hasMore: explicitMore ?? rows.length >= limit,
    nextOffset: offset + rows.length,
  };
}

/** DELETE /uploads/{asset_id} — remove an uploaded asset (row + stored object). */
export async function deleteUpload(assetId: string, options?: RequestOptions): Promise<void> {
  await request<unknown>(`/uploads/${encodeURIComponent(assetId)}`, {
    method: "DELETE",
    options,
  });
}

// ---------------------------------------------------------------------------
// Pending workspace invites + accept links
// ---------------------------------------------------------------------------

export interface WorkspaceInvite {
  id: string;
  email: string;
  role: WorkspaceRole;
  /**
   * One-time accept token. Only returned when the invite is created (the
   * server stores a hash), so listed invites carry no token or link.
   */
  token?: string;
  /** Link the invitee opens to join; empty when no token is available. */
  accept_url: string;
  status: string;
  workspace_id?: string;
  workspace_name?: string;
  created_at?: string;
  expires_at?: string;
  /** True when the invitee already has an account and got an in-app notice. */
  notified_in_app?: boolean;
}

/** Build the web accept link for a token on the current origin. */
export function inviteAcceptUrl(token: string): string {
  const origin =
    typeof window === "undefined" ? "https://menivor.com" : window.location.origin;
  return `${origin}/invite/${encodeURIComponent(token)}`;
}

function normalizeInvite(raw: unknown): WorkspaceInvite | null {
  if (!isObject(raw)) return null;
  const inner = isObject(raw.invite) ? raw.invite : raw;
  const id = str(inner.id) ?? str(inner.invite_id) ?? str(inner.token);
  const email = str(inner.email);
  if (!id || !email) return null;
  const token = str(inner.token);
  const serverUrl = str(raw.accept_url) ?? str(inner.accept_url);
  // The web app owns the accept page; prefer a link on this origin.
  const acceptUrl = token ? inviteAcceptUrl(token) : (serverUrl ?? "");
  return {
    id,
    email,
    role: (str(inner.role) ?? "member") as WorkspaceRole,
    token,
    accept_url: acceptUrl,
    status: str(inner.status) ?? "pending",
    workspace_id: str(inner.workspace_id),
    workspace_name: str(raw.workspace_name) ?? str(inner.workspace_name),
    created_at: str(inner.created_at),
    expires_at: str(inner.expires_at),
    notified_in_app: raw.notified_in_app === true,
  };
}

/** GET /workspaces/{id}/invites — pending invites (admin+). */
export async function listWorkspaceInvites(
  workspaceId: string,
  options?: RequestOptions,
): Promise<WorkspaceInvite[]> {
  const data = await request<unknown>(
    `/workspaces/${encodeURIComponent(workspaceId)}/invites`,
    { options },
  );
  return pickArray(data, ["invites", "items"])
    .map(normalizeInvite)
    .filter((i): i is WorkspaceInvite => i !== null && i.status === "pending");
}

/**
 * POST /workspaces/{id}/invites — create a pending invite for someone who has
 * no Menivor account yet. Returns the invite with its shareable accept link.
 */
export async function createWorkspaceInvite(
  workspaceId: string,
  body: { email: string; role?: AssignableWorkspaceRole },
  options?: RequestOptions,
): Promise<WorkspaceInvite> {
  const data = await request<unknown>(
    `/workspaces/${encodeURIComponent(workspaceId)}/invites`,
    { method: "POST", body, options },
  );
  const invite = normalizeInvite(data);
  if (!invite) throw new Error("The server did not return an invite link.");
  return invite;
}

/** DELETE /workspaces/{id}/invites/{inviteId} — revoke a pending invite. */
export async function revokeWorkspaceInvite(
  workspaceId: string,
  inviteId: string,
  options?: RequestOptions,
): Promise<void> {
  await request<unknown>(
    `/workspaces/${encodeURIComponent(workspaceId)}/invites/${encodeURIComponent(inviteId)}`,
    { method: "DELETE", options },
  );
}

/** Result of POST /workspaces/{id}/invite: an immediate member or a pending invite. */
export type InviteOutcome =
  | { kind: "member"; member: Member }
  | { kind: "pending"; invite: WorkspaceInvite };

/** Classify an invite-endpoint response (member row vs pending invite). */
export function toInviteOutcome(data: unknown): InviteOutcome | null {
  if (isObject(data) && str(data.user_id)) {
    return { kind: "member", member: data as unknown as Member };
  }
  if (isObject(data) && isObject(data.member) && str(data.member.user_id)) {
    return { kind: "member", member: data.member as unknown as Member };
  }
  const invite = normalizeInvite(data);
  return invite ? { kind: "pending", invite } : null;
}

/** Public preview of an invite, for the accept page. */
export interface InvitePreview {
  workspace_id?: string;
  workspace_name: string;
  role: WorkspaceRole;
  email?: string;
  invited_by?: string;
  status: string;
  expires_at?: string;
}

/** GET /invites/{token} — public preview of what the invite grants. */
export async function getInvite(token: string, options?: RequestOptions): Promise<InvitePreview> {
  const data = await request<unknown>(`/invites/${encodeURIComponent(token)}`, {
    options,
    anonymous: true,
  });
  const inner = isObject(data) && isObject(data.invite) ? data.invite : isObject(data) ? data : {};
  const workspace = isObject(inner.workspace) ? inner.workspace : {};
  return {
    workspace_id: str(inner.workspace_id) ?? str(workspace.id),
    workspace_name: str(inner.workspace_name) ?? str(workspace.name) ?? "a Menivor workspace",
    role: (str(inner.role) ?? "member") as WorkspaceRole,
    email: str(inner.email_hint) ?? str(inner.email),
    invited_by: str(inner.invited_by_email) ?? str(inner.inviter_email),
    status: str(inner.status) ?? "pending",
    expires_at: str(inner.expires_at),
  };
}

/** POST /invites/{token}/accept — join the workspace as the signed-in caller. */
export async function acceptInvite(
  token: string,
  options?: RequestOptions,
): Promise<{ workspace_id?: string }> {
  const data = await request<unknown>(`/invites/${encodeURIComponent(token)}/accept`, {
    method: "POST",
    options,
  });
  const workspace = isObject(data) && isObject(data.workspace) ? data.workspace : {};
  return {
    workspace_id:
      (isObject(data) ? str(data.workspace_id) : undefined) ?? str(workspace.id),
  };
}

/** GET /me/invites — pending invitations addressed to the caller's email. */
export async function listMyInvites(options?: RequestOptions): Promise<WorkspaceInvite[]> {
  const data = await request<unknown>("/me/invites", { options });
  return pickArray(data, ["invites", "items"])
    .map(normalizeInvite)
    .filter((i): i is WorkspaceInvite => i !== null && i.status === "pending");
}

/** POST /me/invites/{inviteId}/accept — join from the caller's invitation inbox. */
export async function acceptMyInvite(
  inviteId: string,
  options?: RequestOptions,
): Promise<{ workspace_id?: string }> {
  const data = await request<unknown>(`/me/invites/${encodeURIComponent(inviteId)}/accept`, {
    method: "POST",
    options,
  });
  const workspace = isObject(data) && isObject(data.workspace) ? data.workspace : {};
  return {
    workspace_id:
      (isObject(data) ? str(data.workspace_id) : undefined) ?? str(workspace.id),
  };
}

/**
 * POST /workspaces/{id}/invite — invite by email. An existing account joins
 * immediately (`member`); anyone else gets a pending invite whose one-time
 * accept link the admin shares (`pending`). No invite email is sent.
 */
export async function inviteToWorkspace(
  workspaceId: string,
  body: { email: string; role?: AssignableWorkspaceRole },
  options?: RequestOptions,
): Promise<InviteOutcome> {
  const data = await request<unknown>(
    `/workspaces/${encodeURIComponent(workspaceId)}/invite`,
    { method: "POST", body, options },
  );
  const outcome = toInviteOutcome(data);
  if (!outcome) throw new Error("The server returned an unexpected invite response.");
  return outcome;
}
