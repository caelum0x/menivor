/** Agency clients — modeled on the real workspaces backend (each workspace = a client). */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface Client {
  id: string;
  name: string;
  owner_id: string;
  role: string; // owner | admin | member
  created_at: string | null;
}

export function listClients(options?: RequestOptions): Promise<Client[]> {
  return apiRequest<Client[]>("/me/workspaces", { options });
}

export function createClient(name: string, options?: RequestOptions): Promise<Client> {
  return apiRequest<Client>("/workspaces", { method: "POST", body: { name }, options });
}

export function inviteToClient(
  workspaceId: string,
  email: string,
  role: string,
  options?: RequestOptions,
): Promise<{ user_id?: string; role: string }> {
  return apiRequest(`/workspaces/${encodeURIComponent(workspaceId)}/members`, {
    method: "POST",
    body: { email, role },
    options,
  });
}

export interface Member {
  user_id: string;
  email: string | null;
  role: string;
  created_at: string | null;
}

export function listMembers(workspaceId: string, options?: RequestOptions): Promise<Member[]> {
  return apiRequest<Member[]>(`/workspaces/${encodeURIComponent(workspaceId)}/members`, { options });
}

export function inviteMember(
  workspaceId: string,
  email: string,
  role: string,
  options?: RequestOptions,
): Promise<Member> {
  return apiRequest<Member>(`/workspaces/${encodeURIComponent(workspaceId)}/invite`, {
    method: "POST",
    body: { email, role },
    options,
  });
}

export function getCredits(workspaceId: string, options?: RequestOptions): Promise<{ balance: number }> {
  return apiRequest<{ balance: number }>(`/workspaces/${encodeURIComponent(workspaceId)}/credits`, { options });
}

export function grantCredits(
  workspaceId: string,
  amount: number,
  options?: RequestOptions,
): Promise<{ balance: number }> {
  return apiRequest<{ balance: number }>(`/workspaces/${encodeURIComponent(workspaceId)}/credits/grant`, {
    method: "POST",
    body: { amount },
    options,
  });
}
