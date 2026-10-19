/**
 * Typed client for the unified publishing calendar and the Telegram / Discord /
 * Mastodon channels. Mirrors:
 *
 * - apps/api/app/domains/publishing/native_router.py  (/publishing/calendar/*)
 * - apps/api/app/domains/publishing/extended/channels_router.py
 *   (/publishing/channels*, /publishing/channel-posts)
 *
 * Every response is token-free. All times are UTC ISO-8601 instants; the UI
 * renders them in the viewer's timezone. The API is a system boundary, so
 * entries are normalized and malformed rows dropped.
 */

import { ApiError, apiRequest, type RequestOptions } from "@/src/shared/api";
import { readableApiError } from "@/src/shared/launch-gate/gate";

export { ApiError };

export type EntrySource = "native" | "post";

export interface BoardEntry {
  source: EntrySource;
  id: string;
  job_id: string | null;
  platforms: string[];
  labels: string[];
  scheduled_at: string | null;
  status: string;
  text: string;
  url: string;
  error: string;
  target_id: string;
  channel_label: string;
  can_move: boolean;
}

export interface BoardWindow {
  entries: BoardEntry[];
  best_hours_utc: Record<string, number[]>;
}

export interface PlatformVerdict {
  platform: string;
  label: string;
  allow: boolean;
  reason: string;
  suggested_at: string | null;
}

export interface SlotCheck {
  allow: boolean;
  reason: string;
  suggested_at: string | null;
  platforms: PlatformVerdict[];
  best_hours_utc: Record<string, number[]>;
}

export interface MoveResult {
  entry: BoardEntry;
  check: SlotCheck;
  forced: boolean;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function strList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string" && v.length > 0)
    : [];
}

function hoursMap(value: unknown): Record<string, number[]> {
  if (!value || typeof value !== "object") return {};
  const out: Record<string, number[]> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (Array.isArray(raw)) {
      out[key] = raw.filter(
        (h): h is number => typeof h === "number" && h >= 0 && h < 24,
      );
    }
  }
  return out;
}

export function normalizeEntry(raw: unknown): BoardEntry | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const id = str(r.id);
  const source = r.source === "native" || r.source === "post" ? r.source : null;
  if (!id || !source) return null;
  return {
    source,
    id,
    job_id: str(r.job_id) || null,
    platforms: strList(r.platforms),
    labels: strList(r.labels),
    scheduled_at: str(r.scheduled_at) || null,
    status: str(r.status) || "pending",
    text: str(r.text),
    url: str(r.url),
    error: str(r.error),
    target_id: str(r.target_id),
    channel_label: str(r.channel_label),
    can_move: r.can_move === true,
  };
}

export function normalizeCheck(raw: unknown): SlotCheck | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const verdicts = Array.isArray(r.platforms) ? r.platforms : [];
  return {
    allow: r.allow === true,
    reason: str(r.reason),
    suggested_at: str(r.suggested_at) || null,
    platforms: verdicts
      .filter((v): v is Record<string, unknown> => !!v && typeof v === "object")
      .map((v) => ({
        platform: str(v.platform),
        label: str(v.label) || str(v.platform),
        allow: v.allow === true,
        reason: str(v.reason),
        suggested_at: str(v.suggested_at) || null,
      })),
    best_hours_utc: hoursMap(r.best_hours_utc),
  };
}

/** The slot check carried in a 409 from a refused move (null for other errors). */
export function conflictCheckOf(err: unknown): SlotCheck | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const detail = err.detail as { data?: { check?: unknown } } | undefined;
  return normalizeCheck(detail?.data?.check);
}

export async function getBoard(
  startISO: string,
  endISO: string,
  options?: RequestOptions,
): Promise<BoardWindow> {
  const query = new URLSearchParams({ start: startISO, end: endISO });
  const data = await apiRequest<{ entries?: unknown[]; best_hours_utc?: unknown }>(
    `/publishing/calendar/entries?${query.toString()}`,
    { options },
  );
  return {
    entries: (data?.entries ?? [])
      .map(normalizeEntry)
      .filter((e): e is BoardEntry => e !== null),
    best_hours_utc: hoursMap(data?.best_hours_utc),
  };
}

export async function checkSlot(
  entry: Pick<BoardEntry, "source" | "id">,
  scheduledAtISO: string,
  options?: RequestOptions,
): Promise<SlotCheck> {
  const data = await apiRequest<unknown>("/publishing/calendar/check", {
    method: "POST",
    body: { source: entry.source, id: entry.id, scheduled_at: scheduledAtISO },
    options,
  });
  const check = normalizeCheck(data);
  if (!check) throw new ApiError("Malformed slot check response.", 200, data);
  return check;
}

export async function moveEntry(
  entry: Pick<BoardEntry, "source" | "id">,
  scheduledAtISO: string,
  force: boolean,
  options?: RequestOptions,
): Promise<MoveResult> {
  const data = await apiRequest<{ entry?: unknown; check?: unknown; forced?: unknown }>(
    `/publishing/calendar/entries/${entry.source}/${encodeURIComponent(entry.id)}`,
    { method: "PATCH", body: { scheduled_at: scheduledAtISO, force }, options },
  );
  const moved = normalizeEntry(data?.entry);
  const check = normalizeCheck(data?.check);
  if (!moved || !check) {
    throw new ApiError("Malformed response: expected the moved entry.", 200, data);
  }
  return { entry: moved, check, forced: data?.forced === true };
}

// ---------------------------------------------------------------------------
// Tone preview
// ---------------------------------------------------------------------------

export type Tone = "as_written" | "professional" | "casual" | "concise";

export const TONES: readonly { id: Tone; label: string }[] = [
  { id: "as_written", label: "As written" },
  { id: "professional", label: "Professional" },
  { id: "casual", label: "Casual" },
  { id: "concise", label: "Concise" },
];

export interface FormatIssue {
  level: "warning" | "error";
  field: string;
  message: string;
}

export interface PlatformPreview {
  platform: string;
  label: string;
  text: string;
  title: string;
  length: number;
  limit: number;
  ok: boolean;
  issues: FormatIssue[];
}

export async function previewTone(
  input: {
    caption: string;
    hashtags: string[];
    tone: Tone;
    platforms: string[];
  },
  options?: RequestOptions,
): Promise<{ caption: string; previews: PlatformPreview[] }> {
  const data = await apiRequest<{ caption?: unknown; previews?: unknown[] }>(
    "/publishing/calendar/preview",
    { method: "POST", body: input, options },
  );
  const previews = (data?.previews ?? [])
    .filter((p): p is Record<string, unknown> => !!p && typeof p === "object")
    .map((p) => ({
      platform: str(p.platform),
      label: str(p.label) || str(p.platform),
      text: str(p.text),
      title: str(p.title),
      length: typeof p.length === "number" ? p.length : 0,
      limit: typeof p.limit === "number" ? p.limit : 0,
      ok: p.ok !== false,
      issues: (Array.isArray(p.issues) ? p.issues : [])
        .filter((i): i is Record<string, unknown> => !!i && typeof i === "object")
        .map((i) => ({
          level: i.level === "error" ? ("error" as const) : ("warning" as const),
          field: str(i.field),
          message: str(i.message),
        })),
    }));
  return { caption: str(data?.caption), previews };
}

// ---------------------------------------------------------------------------
// Channels
// ---------------------------------------------------------------------------

export type ChannelKind = "telegram" | "discord" | "mastodon";

export interface Channel {
  id: string;
  kind: ChannelKind;
  kind_label: string;
  label: string;
  status: "connected" | "needs_reauth" | "error" | string;
  target_id: string;
  target_name: string;
  instance_url: string;
  shared: boolean;
  mine: boolean;
  can_post: boolean;
  can_manage: boolean;
  public_url: string;
  inbox: { reads: boolean; note: string };
  caption_max: number;
  last_verified_at: string | null;
  last_error: string;
}

export interface ChannelKindInfo {
  kind: ChannelKind;
  label: string;
  help: string;
  docs_url: string;
  cost_note: string;
  rules: { caption_max: number; max_bytes: number; aspect_note: string };
}

export interface ChannelsOverview {
  channels: Channel[];
  kinds: ChannelKindInfo[];
}

export interface ChannelPost {
  id: string;
  platform: string;
  status: string;
  scheduled_at: string | null;
  url: string;
  error: string;
  target_id: string;
  channel_label?: string;
}

export function getChannels(options?: RequestOptions): Promise<ChannelsOverview> {
  return apiRequest<ChannelsOverview>("/publishing/channels", { options }).then(
    (data) => ({
      channels: Array.isArray(data?.channels) ? data.channels : [],
      kinds: Array.isArray(data?.kinds) ? data.kinds : [],
    }),
  );
}

export type ConnectInput =
  | { kind: "telegram"; bot_token: string; chat_id: string; label?: string }
  | {
      kind: "discord";
      webhook_url: string;
      bot_token?: string;
      channel_id?: string;
      label?: string;
    }
  | {
      kind: "mastodon";
      instance: string;
      access_token: string;
      visibility?: "public" | "unlisted" | "private";
      label?: string;
    };

export function connectChannel(
  input: ConnectInput,
  options?: RequestOptions,
): Promise<Channel> {
  const { kind, ...body } = input;
  return apiRequest<Channel>(`/publishing/channels/${kind}`, {
    method: "POST",
    body,
    options,
  });
}

export function verifyChannel(id: string, options?: RequestOptions): Promise<Channel> {
  return apiRequest<Channel>(`/publishing/channels/${encodeURIComponent(id)}/verify`, {
    method: "POST",
    options,
  });
}

export function testChannel(
  id: string,
  text: string,
  options?: RequestOptions,
): Promise<ChannelPost> {
  return apiRequest<ChannelPost>(`/publishing/channels/${encodeURIComponent(id)}/test`, {
    method: "POST",
    body: { text },
    options,
  });
}

export function disconnectChannel(
  id: string,
  options?: RequestOptions,
): Promise<{ canceled_posts: number }> {
  return apiRequest<{ canceled_posts: number }>(
    `/publishing/channels/${encodeURIComponent(id)}`,
    { method: "DELETE", options },
  );
}

export function createChannelPosts(
  input: {
    drafts: { channel_id: string; caption: string; hashtags: string[] }[];
    job_id?: string;
    scheduled_at?: string | null;
    tone?: Tone;
  },
  options?: RequestOptions,
): Promise<{ posts: ChannelPost[] }> {
  return apiRequest<{ posts: ChannelPost[] }>("/publishing/channel-posts", {
    method: "POST",
    body: input,
    options,
  });
}

/** Problems listed by a 409 from the channel endpoints (`data.problems`). */
export function problemsOf(err: unknown): { channel_id?: string; message: string }[] {
  if (!(err instanceof ApiError)) return [];
  const detail = err.detail as { data?: { problems?: unknown } } | undefined;
  const list = detail?.data?.problems;
  return Array.isArray(list)
    ? list
        .filter((p): p is Record<string, unknown> => !!p && typeof p === "object")
        .map((p) => ({ channel_id: str(p.channel_id), message: str(p.message) }))
    : [];
}

export function errorMessage(err: unknown, fallback: string): string {
  // Strips the request-id prefix and maps launch-gate refusals to readable copy.
  return readableApiError(err, fallback);
}
