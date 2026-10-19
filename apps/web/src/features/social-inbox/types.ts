/** Social inbox API shapes (mirror apps/api/app/domains/social_inbox/views.py). */

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
export type PostInboxState =
  | "ok"
  | "not_connected"
  | "missing_permission"
  | "not_offered"
  | "error";

export const INBOX_PLATFORMS: readonly InboxPlatform[] = [
  "youtube",
  "instagram",
  "tiktok",
  "facebook",
  "threads",
  "bluesky",
  "linkedin",
  "x",
  "pinterest",
  "telegram",
  "discord",
  "mastodon",
];

/** Credential channels, connected on the calendar's Channels page. */
export const CHANNEL_INBOX_PLATFORMS: ReadonlySet<InboxPlatform> = new Set<InboxPlatform>([
  "telegram",
  "discord",
  "mastodon",
]);

/** Platforms connected on the Connections page's "More platforms" section. */
export const EXTENDED_INBOX_PLATFORMS: ReadonlySet<InboxPlatform> = new Set<InboxPlatform>([
  "facebook",
  "threads",
  "bluesky",
  "linkedin",
  "x",
  "pinterest",
]);

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

export interface InboxPostCounts {
  platform_comments: number | null;
  platform_likes: number | null;
  platform_views: number | null;
  synced_comments: number;
  needs_reply: number;
  replied: number;
}

export interface InboxPost {
  id: string;
  platform: InboxPlatform;
  platform_label: string;
  kind: "post" | "dm_channel";
  job_id: string | null;
  external_id: string;
  title: string;
  url: string;
  posted_at: string | null;
  inbox_state: PostInboxState;
  state_note: string;
  counts: InboxPostCounts;
  last_polled_at: string | null;
  next_poll_at: string | null;
}

export interface InboxOverview {
  platforms: PlatformCapability[];
  posts: InboxPost[];
  totals: {
    by_status: Record<ThreadStatus, number>;
    needs_reply_by_platform: Record<InboxPlatform, number>;
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
  last_inbound_at: string | null;
  replied_at: string | null;
  reply_via: string;
  reply_text: string;
  reply: ReplyMode;
}

export interface InboxThreadDetail extends InboxThread {
  messages: InboxMessage[];
  post: InboxPost | null;
}

export interface ThreadPage {
  threads: InboxThread[];
  total: number;
  limit: number;
  offset: number;
}

export interface ThreadFilters {
  platform: "" | InboxPlatform;
  postId: string;
  status: ThreadStatus | "all";
  kind: "" | ThreadKind;
}

export interface ReplySuggestions {
  suggestions: string[];
  source: "ai" | "template";
  intent: string;
}
