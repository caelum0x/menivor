/**
 * Pending workspace invites + shareable accept links — Expo.
 *
 * Owners/admins invite someone who has no Menivor account yet with
 * `POST /workspaces/{id}/invites`; the response carries an opaque token whose
 * accept link (https://menivor.com/invite/<token>) can be shared from the
 * device. Pending invites are listed (`GET /workspaces/{id}/invites`) and can
 * be revoked (`DELETE /workspaces/{id}/invites/{inviteId}`). The invitee opens
 * the link, signs in, previews it (`GET /invites/{token}`) and joins
 * (`POST /invites/{token}/accept`). Mirrors web `lib/library-api.ts`.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";
import type { WorkspaceRole } from "@/lib/types";

/** Public web origin that owns the accept page (also an associated domain). */
const INVITE_ORIGIN = (process.env.EXPO_PUBLIC_WEB_ORIGIN || "https://menivor.com").replace(/\/+$/, "");

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
}

function pickArray(data: unknown, keys: readonly string[]): unknown[] {
  if (Array.isArray(data)) return data;
  if (!isObject(data)) return [];
  for (const key of keys) {
    const value = data[key];
    if (Array.isArray(value)) return value;
  }
  return [];
}

export interface WorkspaceInvite {
  id: string;
  email: string;
  role: WorkspaceRole;
  token?: string;
  /** Shareable link the invitee opens to join. */
  acceptUrl: string;
  status: string;
  createdAt?: string;
  expiresAt?: string;
}

export interface InvitePreview {
  workspaceId?: string;
  workspaceName: string;
  role: WorkspaceRole;
  email?: string;
  invitedBy?: string;
  status: string;
  expiresAt?: string;
}

/** The web accept link for an invite token. */
export function inviteAcceptUrl(token: string): string {
  return `${INVITE_ORIGIN}/invite/${encodeURIComponent(token)}`;
}

/**
 * POST /workspaces/{id}/members (and /invite) answers 200 with a pending
 * invite (`pending: true`) when the email has no account yet. Returns that
 * invite, or null when the response is a real membership row.
 */
export function pendingInviteFromResponse(raw: unknown): WorkspaceInvite | null {
  if (!isObject(raw) || raw.pending !== true) return null;
  return normalizeInvite(raw);
}

function normalizeInvite(raw: unknown): WorkspaceInvite | null {
  if (!isObject(raw)) return null;
  const inner = isObject(raw.invite) ? raw.invite : raw;
  const id = str(inner.id) ?? str(inner.invite_id) ?? str(inner.token);
  const email = str(inner.email);
  if (!id || !email) return null;
  const token = str(inner.token);
  const serverUrl = str(raw.accept_url) ?? str(inner.accept_url);
  return {
    id,
    email,
    role: (str(inner.role) ?? "member") as WorkspaceRole,
    token,
    acceptUrl: token ? inviteAcceptUrl(token) : serverUrl ?? "",
    status: str(inner.status) ?? "pending",
    createdAt: str(inner.created_at),
    expiresAt: str(inner.expires_at),
  };
}

/** GET /workspaces/{id}/invites — pending invites (owner/admin). */
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

/** POST /workspaces/{id}/invites — invite someone without an account yet. */
export async function createWorkspaceInvite(
  workspaceId: string,
  body: { email: string; role?: WorkspaceRole },
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

/** GET /invites/{token} — what the invite grants (no membership change). */
export async function getInvite(token: string, options?: RequestOptions): Promise<InvitePreview> {
  const data = await request<unknown>(`/invites/${encodeURIComponent(token)}`, { options });
  const inner = isObject(data) && isObject(data.invite) ? data.invite : isObject(data) ? data : {};
  const workspace = isObject(inner.workspace) ? inner.workspace : {};
  return {
    workspaceId: str(inner.workspace_id) ?? str(workspace.id),
    workspaceName: str(inner.workspace_name) ?? str(workspace.name) ?? "a Menivor workspace",
    role: (str(inner.role) ?? "member") as WorkspaceRole,
    email: str(inner.email),
    invitedBy: str(inner.invited_by) ?? str(inner.inviter_email),
    status: str(inner.status) ?? "pending",
    expiresAt: str(inner.expires_at),
  };
}

/** POST /invites/{token}/accept — join the workspace as the signed-in caller. */
export async function acceptInvite(
  token: string,
  options?: RequestOptions,
): Promise<{ workspaceId?: string }> {
  const data = await request<unknown>(`/invites/${encodeURIComponent(token)}/accept`, {
    method: "POST",
    options,
  });
  const inner = isObject(data) && isObject(data.workspace) ? data.workspace : isObject(data) ? data : {};
  return { workspaceId: str(inner.workspace_id) ?? str(inner.id) };
}
