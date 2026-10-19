/**
 * Telegram / Discord / Mastodon channel client for Expo. Mirrors the web client
 * (apps/web/components/calendar/board-api.ts) and the API routes in
 * apps/api/app/domains/publishing/extended/channels_router.py plus the unified
 * calendar read in apps/api/app/domains/publishing/native_router.py:
 *
 *   GET    /publishing/channels                  connected channels + kinds
 *   POST   /publishing/channels/{kind}           connect (credential verified first)
 *   POST   /publishing/channels/{id}/verify      re-check the credential
 *   POST   /publishing/channels/{id}/test        send a short test post now
 *   DELETE /publishing/channels/{id}             disconnect (cancels queued posts)
 *   POST   /publishing/channel-posts             post now or schedule
 *   GET    /publishing/calendar/entries          the queue (filtered to channels)
 *
 * Responses never carry tokens. Times crossing this boundary are UTC ISO-8601.
 * The pure helpers (normalisers, form validation, queue filter) are
 * unit-tested under node.
 */

import { ApiError, apiRequest, type RequestOptions } from "@/src/shared/api/client";

export type ChannelKind = "telegram" | "discord" | "mastodon";
export const CHANNEL_KINDS: readonly ChannelKind[] = ["telegram", "discord", "mastodon"];

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

/** One post in the unified calendar (`source: "post"` rows carry channel posts). */
export interface QueueEntry {
  source: "native" | "post";
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

export type ConnectInput =
  | { kind: "telegram"; bot_token: string; chat_id: string; label?: string }
  | { kind: "discord"; webhook_url: string; bot_token?: string; channel_id?: string; label?: string }
  | {
      kind: "mastodon";
      instance: string;
      access_token: string;
      visibility?: MastodonVisibility;
      label?: string;
    };

export type MastodonVisibility = "public" | "unlisted" | "private";

/** Server caps (ChannelDraftBody / ChannelPostsBody). */
export const CAPTION_MAX = 4096;
export const HASHTAGS_MAX = 30;
export const MAX_CHANNELS_PER_POST = 10;
/** Days of history and future the queue view loads (backend clamps at 92). */
export const QUEUE_PAST_DAYS = 7;
export const QUEUE_FUTURE_DAYS = 60;

// ---------------------------------------------------------------------------
// Requests
// ---------------------------------------------------------------------------

export async function getChannels(options?: RequestOptions): Promise<ChannelsOverview> {
  const data = await apiRequest<Partial<ChannelsOverview> | null>("/publishing/channels", { options });
  return {
    channels: Array.isArray(data?.channels) ? data.channels : [],
    kinds: Array.isArray(data?.kinds) ? data.kinds : [],
  };
}

export function connectChannel(input: ConnectInput, options?: RequestOptions): Promise<Channel> {
  const { kind, ...body } = input;
  return apiRequest<Channel>(`/publishing/channels/${kind}`, { method: "POST", body, options });
}

export function verifyChannel(id: string, options?: RequestOptions): Promise<Channel> {
  return apiRequest<Channel>(`/publishing/channels/${encodeURIComponent(id)}/verify`, {
    method: "POST",
    options,
  });
}

export function testChannel(id: string, text: string, options?: RequestOptions): Promise<ChannelPost> {
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
  return apiRequest<{ canceled_posts: number }>(`/publishing/channels/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
}

export interface ChannelPostsInput {
  drafts: { channel_id: string; caption: string; hashtags: string[] }[];
  scheduled_at?: string | null;
}

export async function createChannelPosts(
  input: ChannelPostsInput,
  options?: RequestOptions,
): Promise<ChannelPost[]> {
  const data = await apiRequest<{ posts?: ChannelPost[] } | null>("/publishing/channel-posts", {
    method: "POST",
    body: input,
    options,
  });
  return Array.isArray(data?.posts) ? data.posts : [];
}

/** Channel posts from the unified calendar, in a window around `now`. */
export async function getChannelQueue(
  channelIds: ReadonlySet<string>,
  options?: RequestOptions,
  now: Date = new Date(),
): Promise<QueueEntry[]> {
  const { start, end } = queueWindow(now);
  const query = new URLSearchParams({ start, end });
  const data = await apiRequest<{ entries?: unknown[] } | null>(
    `/publishing/calendar/entries?${query.toString()}`,
    { options },
  );
  const entries = (data?.entries ?? [])
    .map(normalizeEntry)
    .filter((e): e is QueueEntry => e !== null);
  return channelQueue(entries, channelIds);
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function strList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string" && v.length > 0)
    : [];
}

/** The API is a system boundary: drop malformed rows, default missing fields. */
export function normalizeEntry(raw: unknown): QueueEntry | null {
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

export function queueWindow(now: Date): { start: string; end: string } {
  const day = 24 * 60 * 60 * 1000;
  return {
    start: new Date(now.getTime() - QUEUE_PAST_DAYS * day).toISOString(),
    end: new Date(now.getTime() + QUEUE_FUTURE_DAYS * day).toISOString(),
  };
}

/**
 * Keep only posts aimed at a connected channel (or labelled as one), sorted
 * by scheduled time, latest first.
 */
export function channelQueue(entries: readonly QueueEntry[], channelIds: ReadonlySet<string>): QueueEntry[] {
  const time = (e: QueueEntry) => (e.scheduled_at ? Date.parse(e.scheduled_at) || 0 : 0);
  return entries
    .filter(
      (e) =>
        e.source === "post" &&
        ((e.target_id !== "" && channelIds.has(e.target_id)) || e.channel_label !== ""),
    )
    .slice()
    .sort((a, b) => time(b) - time(a));
}

/** Split `#a, b  #c` into de-duplicated tags without the leading `#`, capped. */
export function parseHashtags(input: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const piece of input.split(/[\s,]+/)) {
    const tag = piece.replace(/^#+/, "").trim();
    if (!tag || seen.has(tag.toLowerCase())) continue;
    seen.add(tag.toLowerCase());
    out.push(tag);
    if (out.length >= HASHTAGS_MAX) break;
  }
  return out;
}

export interface ComposeCheck {
  ok: boolean;
  reason: string;
}

/** Validate a channel post before sending; mirrors the server caps. */
export function checkCompose(
  selected: readonly Channel[],
  caption: string,
  scheduledAt: Date | null,
  now: Date = new Date(),
): ComposeCheck {
  if (selected.length === 0) return { ok: false, reason: "Pick at least one channel." };
  if (selected.length > MAX_CHANNELS_PER_POST) {
    return { ok: false, reason: `Pick at most ${MAX_CHANNELS_PER_POST} channels per post.` };
  }
  const text = caption.trim();
  if (!text) return { ok: false, reason: "Write something to post." };
  const tightest = Math.min(
    CAPTION_MAX,
    ...selected.map((c) => (c.caption_max > 0 ? c.caption_max : CAPTION_MAX)),
  );
  if (text.length > tightest) {
    return { ok: false, reason: `Keep it under ${tightest} characters for the selected channels.` };
  }
  const blocked = selected.find((c) => !c.can_post);
  if (blocked) return { ok: false, reason: `${blocked.label} can't be posted to. Re-check it first.` };
  if (scheduledAt && scheduledAt.getTime() <= now.getTime()) {
    return { ok: false, reason: "Pick a time in the future, or post now." };
  }
  return { ok: true, reason: "" };
}

export function buildPostsInput(
  selected: readonly Channel[],
  caption: string,
  hashtags: readonly string[],
  scheduledAt: Date | null,
): ChannelPostsInput {
  const drafts = selected.map((c) => ({
    channel_id: c.id,
    caption: caption.trim().slice(0, CAPTION_MAX),
    hashtags: hashtags.slice(0, HASHTAGS_MAX),
  }));
  return scheduledAt ? { drafts, scheduled_at: scheduledAt.toISOString() } : { drafts };
}

export interface ConnectFields {
  bot_token: string;
  chat_id: string;
  webhook_url: string;
  channel_id: string;
  instance: string;
  access_token: string;
  visibility: MastodonVisibility;
  label: string;
}

export const BLANK_FIELDS: ConnectFields = {
  bot_token: "",
  chat_id: "",
  webhook_url: "",
  channel_id: "",
  instance: "",
  access_token: "",
  visibility: "public",
  label: "",
};

export function toConnectInput(kind: ChannelKind, f: ConnectFields): ConnectInput {
  if (kind === "telegram") {
    return { kind, bot_token: f.bot_token.trim(), chat_id: f.chat_id.trim(), label: f.label.trim() };
  }
  if (kind === "discord") {
    return {
      kind,
      webhook_url: f.webhook_url.trim(),
      bot_token: f.bot_token.trim(),
      channel_id: f.channel_id.trim(),
      label: f.label.trim(),
    };
  }
  return {
    kind,
    instance: f.instance.trim(),
    access_token: f.access_token.trim(),
    visibility: f.visibility,
    label: f.label.trim(),
  };
}

/** Same client-side minimums as the web connect form. */
export function connectReady(kind: ChannelKind, f: ConnectFields): boolean {
  if (kind === "telegram") return f.bot_token.trim().length >= 20 && f.chat_id.trim().length >= 2;
  if (kind === "discord") return f.webhook_url.trim().startsWith("https://");
  return f.instance.trim().length >= 3 && f.access_token.trim().length >= 20;
}

/** Problems listed by a 409 from the channel endpoints (`data.problems`). */
export function problemsOf(err: unknown): { channel_id: string; message: string }[] {
  if (!(err instanceof ApiError)) return [];
  const detail = err.detail as { data?: { problems?: unknown } } | undefined;
  const list = detail?.data?.problems;
  return Array.isArray(list)
    ? list
        .filter((p): p is Record<string, unknown> => !!p && typeof p === "object")
        .map((p) => ({ channel_id: str(p.channel_id), message: str(p.message) }))
    : [];
}

const STATUS_LABELS: Record<string, string> = {
  connected: "Connected",
  needs_reauth: "Reconnect",
  error: "Check failed",
};

export function channelStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}
