/** Channel analytics and team (MV12). */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface TitleStats {
  readonly title_id: string;
  readonly title: string;
  readonly plays: number;
  readonly watch_minutes: number;
  readonly stalls: number;
  readonly errors: number;
  readonly startup_p95_ms: number;
}

export interface Dashboard {
  readonly channel: string;
  readonly days: number;
  readonly totals: { plays: number; watch_minutes: number; stalls: number; errors: number; viewers: number; beacons: number };
  readonly titles: readonly TitleStats[];
  readonly daily: readonly { day: string; plays: number; watch_minutes: number }[];
}

export interface TeamMember {
  readonly id: string;
  readonly email: string;
  readonly role: "editor" | "analyst";
}

export const getDashboard = (days: number, options?: RequestOptions) =>
  apiRequest<Dashboard>(`/ott/studio/analytics?days=${days}`, { options });
export const getTeam = (options?: RequestOptions) => apiRequest<{ members: TeamMember[] }>("/ott/studio/team", { options });
export const addTeamMember = (email: string, role: TeamMember["role"], options?: RequestOptions) =>
  apiRequest<{ members: TeamMember[] }>("/ott/studio/team", { method: "POST", body: { email, role }, options });
export function removeTeamMember(id: string, options?: RequestOptions) {
  const mid = encodeURIComponent(id);
  return apiRequest<{ members: TeamMember[] }>(`/ott/studio/team/${mid}`, { method: "DELETE", options });
}
