/**
 * Brand Agent client: sessions, streamed messages, chips, Brain (brand memory),
 * approval actions, routines, inspirations, skills, folders, library, connectors
 * and the credits meter. Every call goes to `/api/v1/agent/...`.
 */

import { API_BASE, ApiError, apiRequest, resolveApiCredential, type RequestOptions } from "@/src/shared/api";
import { createSseParser } from "./sse";

export type ChipChoice =
  | "yes"
  | "no"
  | "connect"
  | "retry"
  | "skip"
  | "approve"
  | "reject"
  | "use_product"
  | "recheck"
  | "open";

export interface Chip {
  label: string;
  choice: ChipChoice;
  step?: string;
  action_id?: string;
  /** use_product: the picked product id. */
  value?: string;
  /** open: an in-app page that fixes the missing thing (sign in, get credits, connect). */
  href?: string;
}

/** Something an action still needs before Approve is shown (preflight). */
export interface AgentNeed {
  id: "sign_in" | "credits" | "product" | "account" | "video" | "unavailable" | string;
  title: string;
  detail: string;
  options: { id: string; name: string; detail?: string; thumbnail_url?: string }[];
}

export interface AgentAction {
  id: string;
  kind: string;
  status: "pending" | "approved" | "executed" | "rejected" | "failed" | "blocked";
  title: string;
  credits_estimate: number;
  spends_credits: boolean;
  publishes: boolean;
  error: string;
  result: Record<string, unknown> | null;
  needs?: AgentNeed[];
  created_at: string | null;
}

export interface AgentCard {
  type: string;
  step?: string;
  title?: string;
  index?: number | null;
  total?: number;
  data: Record<string, unknown>;
}

export interface AgentMessage {
  id: string;
  seq: number;
  role: "user" | "assistant";
  content: string;
  card: AgentCard | null;
  chips: Chip[];
  action_id: string | null;
  action: AgentAction | null;
  created_at: string | null;
}

export interface AgentSessionInfo {
  id: string;
  space_id: string;
  title: string;
  updated_at: string | null;
}

export interface BrandSpace {
  id: string;
  name: string;
  website_url: string;
}

export interface CreditsMeter {
  balance: number;
  trial_grant: number;
  used: number;
}

export interface Folder {
  id: string;
  name: string;
}

export interface AgentOverview {
  space: BrandSpace;
  spaces: BrandSpace[];
  brain: { version: number; unseen: number; sections: string[] };
  recents: AgentSessionInfo[];
  counts: { pending_actions: number; routines: number; inspirations: number; library: number };
  folders: Folder[];
  credits: CreditsMeter;
}

export interface BrandMemory {
  version: number;
  sections: Record<string, Record<string, unknown>>;
  updated: Record<string, number>;
  unseen: number;
}

export interface Routine {
  id: string;
  name: string;
  skill: string;
  count: number;
  weekday_name: string;
  hour: number;
  enabled: boolean;
  requires_approval: boolean;
  next_run_at: string | null;
}

export interface Inspiration {
  id: string;
  kind: string;
  source: string;
  url: string;
  title: string;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  prompt: string;
  builtin: boolean;
  spends_credits: boolean;
}

export interface LibraryItem {
  id: string;
  kind: string;
  ref: string;
  url: string;
  title: string;
  folder_id: string | null;
  action_id: string | null;
}

export interface Connector {
  id: string;
  name: string;
  status: "connected" | "not_connected" | "unavailable" | "off";
  detail: string;
}

export interface ChipInput {
  choice: Exclude<ChipChoice, "open">;
  step?: string;
  action_id?: string;
  value?: string;
  edits?: Record<string, unknown>;
}

const enc = encodeURIComponent;

export function getOverview(spaceId?: string, options?: RequestOptions): Promise<AgentOverview> {
  const path = spaceId ? `/agent/overview?space_id=${enc(spaceId)}` : "/agent/overview";
  return apiRequest<AgentOverview>(path, { options });
}

export async function createSession(spaceId?: string, options?: RequestOptions): Promise<AgentSessionInfo> {
  const out = await apiRequest<{ session: AgentSessionInfo }>("/agent/sessions", {
    method: "POST",
    body: spaceId ? { space_id: spaceId } : {},
    options,
  });
  return out.session;
}

export function getSession(
  sessionId: string,
  options?: RequestOptions,
): Promise<{ session: AgentSessionInfo; messages: AgentMessage[]; setup: { step: string | null } }> {
  return apiRequest(`/agent/sessions/${sessionId}`, { options });
}

export async function sendMessage(sessionId: string, text: string, options?: RequestOptions): Promise<AgentMessage[]> {
  const out = await apiRequest<{ messages: AgentMessage[] }>(`/agent/sessions/${sessionId}/messages`, {
    method: "POST",
    body: { text },
    options,
  });
  return out.messages;
}

export async function sendChip(sessionId: string, chip: ChipInput, options?: RequestOptions): Promise<AgentMessage[]> {
  const out = await apiRequest<{ messages: AgentMessage[] }>(`/agent/sessions/${sessionId}/chips`, {
    method: "POST",
    body: chip,
    options,
  });
  return out.messages;
}

export interface StreamHandlers {
  onDelta?: (messageId: string, text: string) => void;
  onMessage?: (message: AgentMessage) => void;
}

/**
 * Send text or a chip and read the Server-Sent Events reply. Resolves with the
 * full assistant messages once the stream says `done`.
 */
export async function streamTurn(
  sessionId: string,
  body: { text?: string } & Partial<ChipInput>,
  handlers: StreamHandlers = {},
  options?: RequestOptions,
): Promise<AgentMessage[]> {
  const credential = await resolveApiCredential(options);
  const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "text/event-stream" };
  if (credential) headers["x-api-key"] = credential;
  const path = `/agent/sessions/${sessionId}/stream`;
  const response = await fetch(API_BASE + path, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: options?.signal,
    cache: "no-store",
  });
  if (!response.ok || !response.body) {
    let message = `Request failed with status ${response.status}`;
    try {
      const envelope = (await response.json()) as { message?: string };
      if (envelope?.message) message = envelope.message;
    } catch {
      // keep the generic message
    }
    throw new ApiError(response.status === 401 ? "Your session expired. Sign in again." : message, response.status);
  }
  const parser = createSseParser();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const messages: AgentMessage[] = [];
  for (;;) {
    const { value, done } = await reader.read();
    if (value) {
      for (const evt of parser.push(decoder.decode(value, { stream: true }))) {
        if (evt.event === "delta") {
          const d = evt.data as { message_id: string; text: string };
          handlers.onDelta?.(d.message_id, d.text);
        } else if (evt.event === "message") {
          const message = evt.data as AgentMessage;
          messages.push(message);
          handlers.onMessage?.(message);
        }
      }
    }
    if (done) break;
  }
  return messages;
}

export function getMemory(spaceId: string, options?: RequestOptions): Promise<BrandMemory> {
  return apiRequest<BrandMemory>(`/agent/spaces/${spaceId}/memory`, { options });
}

export function saveMemorySection(
  spaceId: string,
  section: string,
  data: Record<string, unknown>,
  options?: RequestOptions,
): Promise<{ version: number }> {
  return apiRequest(`/agent/spaces/${spaceId}/memory/${section}`, {
    method: "PUT",
    body: { data },
    options,
  });
}

export function markBrainSeen(spaceId: string, options?: RequestOptions): Promise<{ seen_version: number }> {
  return apiRequest(`/agent/spaces/${spaceId}/memory/seen`, { method: "POST", options });
}

export async function decideAction(
  actionId: string,
  decision: "approve" | "reject",
  options?: RequestOptions,
): Promise<AgentAction> {
  const path = decision === "approve" ? `/agent/actions/${actionId}/approve` : `/agent/actions/${actionId}/reject`;
  const out = await apiRequest<{ action: AgentAction }>(path, { method: "POST", options });
  return out.action;
}

export async function listActions(status?: string, options?: RequestOptions): Promise<AgentAction[]> {
  const path = status ? `/agent/actions?status=${enc(status)}` : "/agent/actions";
  return (await apiRequest<{ actions: AgentAction[] }>(path, { options })).actions;
}

export async function listRoutines(options?: RequestOptions): Promise<Routine[]> {
  return (await apiRequest<{ routines: Routine[] }>("/agent/routines", { options })).routines;
}

export async function createRoutine(text: string, options?: RequestOptions): Promise<Routine> {
  return (await apiRequest<{ routine: Routine }>("/agent/routines", { method: "POST", body: { text }, options }))
    .routine;
}

export async function setRoutineEnabled(id: string, enabled: boolean, options?: RequestOptions): Promise<Routine> {
  return (
    await apiRequest<{ routine: Routine }>(`/agent/routines/${id}`, {
      method: "PATCH",
      body: { enabled },
      options,
    })
  ).routine;
}

export async function listInspirations(options?: RequestOptions): Promise<Inspiration[]> {
  return (await apiRequest<{ inspirations: Inspiration[] }>("/agent/inspirations", { options })).inspirations;
}

export async function addInspiration(url: string, options?: RequestOptions): Promise<Inspiration> {
  return (
    await apiRequest<{ inspiration: Inspiration }>("/agent/inspirations", { method: "POST", body: { url }, options })
  ).inspiration;
}

export async function listSkills(options?: RequestOptions): Promise<Skill[]> {
  return (await apiRequest<{ skills: Skill[] }>("/agent/skills", { options })).skills;
}

export async function listLibrary(folderId?: string, options?: RequestOptions): Promise<LibraryItem[]> {
  const path = folderId ? `/agent/library?folder_id=${enc(folderId)}` : "/agent/library";
  return (await apiRequest<{ items: LibraryItem[] }>(path, { options })).items;
}

export async function createFolder(name: string, options?: RequestOptions): Promise<Folder> {
  return (await apiRequest<{ folder: Folder }>("/agent/folders", { method: "POST", body: { name }, options })).folder;
}

export async function listConnectors(options?: RequestOptions): Promise<Connector[]> {
  return (await apiRequest<{ connectors: Connector[] }>("/agent/connectors", { options })).connectors;
}
