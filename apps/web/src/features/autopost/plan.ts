/**
 * Pure helpers for the Autopost batch flow: variation hooks, the campaign
 * request, TikTok posting options and readable statuses. No I/O.
 */

import type {
  Account,
  CampaignBody,
  CreatorInfo,
  PostStatus,
  Provider,
  QueuedPost,
  Visibility,
} from "./api";

/** Opening-hook angles the API accepts (apps/api/app/domains/experiments/hook_styles.py). */
export const HOOK_STYLES = [
  "pov",
  "question",
  "nobody_tells_you",
  "stat",
  "story",
  "met_me_at",
  "nobody_me",
  "wish_i_knew",
  "before_after",
  "tell_me_without",
  "day_in_life",
] as const;

export const MAX_VARIATIONS = HOOK_STYLES.length;
export const MAX_BATCH_VIDEOS = 100;

/** One distinct hook angle per variation (at most one per angle, so no duplicates). */
export function variationHooks(count: number): string[] {
  const n = Math.max(0, Math.min(Math.floor(count), MAX_VARIATIONS));
  return HOOK_STYLES.slice(0, n);
}

export const PROVIDER_LABEL: Record<Provider, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube: "YouTube",
};

export const VISIBILITY_LABEL: Record<Visibility, string> = {
  public: "Everyone",
  friends: "Friends",
  private: "Only me",
};

const TIKTOK_LEVEL: Record<Visibility, string> = {
  public: "PUBLIC_TO_EVERYONE",
  friends: "MUTUAL_FOLLOW_FRIENDS",
  private: "SELF_ONLY",
};

/**
 * Visibility choices every chosen TikTok account allows. Before TikTok
 * approves the app only "Only me" can be used.
 */
export function allowedVisibilities(infos: CreatorInfo[]): Visibility[] {
  const all: Visibility[] = ["public", "friends", "private"];
  if (infos.length === 0) return all;
  if (infos.some((info) => !info.audited)) return ["private"];
  return all.filter((v) =>
    infos.every((info) => info.privacy_level_options.includes(TIKTOK_LEVEL[v])),
  );
}

export interface InteractionLocks {
  comments: boolean;
  duet: boolean;
  stitch: boolean;
}

/** An interaction is locked off when any chosen TikTok account has it switched off. */
export function interactionLocks(infos: CreatorInfo[]): InteractionLocks {
  return {
    comments: infos.some((i) => i.comment_disabled),
    duet: infos.some((i) => i.duet_disabled),
    stitch: infos.some((i) => i.stitch_disabled),
  };
}

/** The declaration under the post button (TikTok's exact wording when TikTok is chosen). */
export function consentText(brandContent: boolean, hasTikTok: boolean): string {
  const own = "I own or have the rights to post these videos on these accounts.";
  if (!hasTikTok) return own;
  const tiktok = brandContent
    ? "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation."
    : "By posting, you agree to TikTok's Music Usage Confirmation.";
  return `${own} ${tiktok}`;
}

export interface BatchForm {
  jobIds: string[];
  accountIds: string[];
  visibility: Visibility | "";
  caption: string;
  hashtags: string;
  mode: "spread" | "every";
  startAt: string;
  tiktokMode: "direct" | "draft";
  allowComments: boolean;
  allowDuet: boolean;
  allowStitch: boolean;
  commercial: boolean;
  yourBrand: boolean;
  brandedContent: boolean;
  consent: boolean;
  name: string;
}

export const EMPTY_FORM: BatchForm = {
  jobIds: [],
  accountIds: [],
  visibility: "",
  caption: "",
  hashtags: "",
  mode: "spread",
  startAt: "",
  tiktokMode: "direct",
  allowComments: false,
  allowDuet: false,
  allowStitch: false,
  commercial: false,
  yourBrand: false,
  brandedContent: false,
  consent: false,
  name: "",
};

export function parseHashtags(raw: string): string[] {
  const tags = raw
    .split(/[\s,]+/)
    .map((t) => t.trim().replace(/^#+/, ""))
    .filter(Boolean);
  return Array.from(new Set(tags)).slice(0, 30);
}

/** Validate the form and build the exact request. Throws a readable Error. */
export function buildCampaignBody(form: BatchForm, nowMs = Date.now()): CampaignBody {
  const jobIds = Array.from(new Set(form.jobIds.filter(Boolean)));
  const accountIds = Array.from(new Set(form.accountIds.filter(Boolean)));
  if (jobIds.length === 0) throw new Error("Choose at least one video.");
  if (jobIds.length > MAX_BATCH_VIDEOS) throw new Error(`Choose at most ${MAX_BATCH_VIDEOS} videos.`);
  if (accountIds.length === 0) throw new Error("Choose at least one account.");
  if (!form.visibility) throw new Error("Choose who can see the posts.");
  if (form.caption.length > 2200) throw new Error("Keep the caption under 2,200 characters.");
  if (form.commercial && !form.yourBrand && !form.brandedContent) {
    throw new Error("Say whether this promotes your brand, a third party, or both.");
  }
  if (form.brandedContent && form.visibility === "private") {
    throw new Error("Branded content cannot be private.");
  }
  if (!form.consent) throw new Error("Confirm the posting terms to continue.");
  let startAt: string | undefined;
  if (form.startAt.trim()) {
    const ms = Date.parse(form.startAt);
    if (!Number.isFinite(ms)) throw new Error("Choose a valid start time.");
    if (ms < nowMs - 60_000) throw new Error("The start time is in the past.");
    startAt = new Date(ms).toISOString();
  }
  return {
    job_ids: jobIds,
    account_ids: accountIds,
    visibility: form.visibility,
    name: form.name.trim() || undefined,
    mode: form.mode,
    start_at: startAt,
    caption: form.caption.trim(),
    hashtags: parseHashtags(form.hashtags),
    tiktok_mode: form.tiktokMode,
    allow_comments: form.allowComments,
    allow_duet: form.allowDuet,
    allow_stitch: form.allowStitch,
    brand_content: form.commercial && form.brandedContent,
    brand_organic: form.commercial && form.yourBrand,
    consent: form.consent,
  };
}

export function postableAccounts(accounts: Account[]): Account[] {
  return accounts.filter((a) => a.status === "connected");
}

const STATUS_TEXT: Record<PostStatus, string> = {
  scheduled: "Scheduled",
  publishing: "Posting",
  processing: "Platform is processing",
  published: "Live",
  failed: "Did not post",
  canceled: "Canceled",
  held: "Held for review",
};

/** A calm, specific line for a queued post. */
export function statusText(post: Pick<QueuedPost, "status" | "provider_status">): string {
  const waiting = post.provider_status || "";
  if (post.status === "scheduled") {
    if (waiting === "waiting_for_video") return "Waiting for the video to finish";
    if (waiting === "account_paused") return "Account paused";
    if (waiting.startsWith("waiting:") || waiting.startsWith("platform_limit")) {
      return "Waiting for the account's posting limit";
    }
    if (waiting === "retrying") return "Will try again shortly";
  }
  if (post.status === "published" && waiting === "SEND_TO_USER_INBOX") return "Sent to TikTok drafts";
  return STATUS_TEXT[post.status] ?? post.status;
}

export function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return "";
  return new Date(ms).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
