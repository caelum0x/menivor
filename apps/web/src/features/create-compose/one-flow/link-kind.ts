/**
 * Instant, offline guess of what a pasted link is, for the one quiet line
 * under the input ("TikTok post detected"). Mirrors the API's classifier
 * (apps/api/app/domains/ingest/classify.py); the API stays the authority and
 * resolves the link when the run starts.
 */

export type LinkKindId = "website" | "app_store" | "play_store" | "social_post" | "social_profile";

export type SocialPlatform =
  | "tiktok"
  | "instagram"
  | "x"
  | "youtube"
  | "facebook"
  | "threads"
  | "pinterest"
  | "linkedin";

export interface LinkKind {
  readonly kind: LinkKindId;
  readonly platform: SocialPlatform | null;
  /** One human line, e.g. "TikTok post detected". */
  readonly label: string;
}

const PLATFORM_NAMES: Readonly<Record<SocialPlatform, string>> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  x: "X",
  youtube: "YouTube",
  facebook: "Facebook",
  threads: "Threads",
  pinterest: "Pinterest",
  linkedin: "LinkedIn",
};

type Rule = (host: string, segments: readonly string[], url: URL) => LinkKindId | null;

const POST: LinkKindId = "social_post";
const PROFILE: LinkKindId = "social_profile";

function first(segments: readonly string[]): string {
  return (segments[0] ?? "").toLowerCase();
}

const IG_RESERVED = new Set(["explore", "accounts", "direct", "stories", "about", "legal", "developer"]);
const X_RESERVED = new Set(["home", "search", "i", "intent", "explore", "notifications", "messages", "settings", "share", "hashtag", "login", "signup", "tos", "privacy"]);
const FB_RESERVED = new Set(["login", "help", "policies", "privacy", "groups", "events", "marketplace", "gaming", "settings", "business"]);
const PIN_RESERVED = new Set(["search", "ideas", "today", "business", "login", "settings", "_"]);

const tiktok: Rule = (host, segs) => {
  if (host === "vm.tiktok.com" || host === "vt.tiktok.com") return segs.length ? POST : null;
  if (segs.includes("video") || segs.includes("photo") || first(segs) === "t") return POST;
  return first(segs).startsWith("@") ? PROFILE : null;
};

const instagram: Rule = (_host, segs) => {
  const head = first(segs);
  if (["p", "reel", "reels", "tv"].includes(head) && segs.length > 1) return POST;
  return head && !IG_RESERVED.has(head) && segs.length === 1 ? PROFILE : null;
};

const x: Rule = (_host, segs) => {
  const head = first(segs);
  if (!head || X_RESERVED.has(head)) return null;
  if (segs[1]?.toLowerCase() === "status" && segs[2]) return POST;
  return segs.length === 1 ? PROFILE : null;
};

const youtube: Rule = (host, segs, url) => {
  const head = first(segs);
  if (host === "youtu.be") return segs.length ? POST : null;
  if (head === "watch" && url.searchParams.get("v")) return POST;
  if (["shorts", "live", "embed"].includes(head) && segs[1]) return POST;
  if (head.startsWith("@")) return PROFILE;
  if (["channel", "c", "user"].includes(head) && segs[1]) return PROFILE;
  return null;
};

const facebook: Rule = (host, segs) => {
  const head = first(segs);
  if (host === "fb.watch") return segs.length ? POST : null;
  if (["watch", "reel", "share", "story.php", "permalink.php"].includes(head)) return POST;
  if (segs.some((s) => ["videos", "posts", "photos", "reels"].includes(s.toLowerCase())) && segs.length > 2) return POST;
  return head && !FB_RESERVED.has(head) && segs.length === 1 ? PROFILE : null;
};

const threads: Rule = (_host, segs) => {
  if (!first(segs).startsWith("@")) return null;
  return segs[1]?.toLowerCase() === "post" && segs[2] ? POST : PROFILE;
};

const pinterest: Rule = (host, segs) => {
  if (host === "pin.it") return segs.length ? POST : null;
  const head = first(segs);
  if (head === "pin" && segs[1]) return POST;
  return head && !PIN_RESERVED.has(head) && segs.length <= 2 ? PROFILE : null;
};

const linkedin: Rule = (_host, segs) => {
  const head = first(segs);
  if (head === "posts" || (head === "feed" && segs[1] === "update")) return POST;
  if (["in", "company"].includes(head) && segs[1]) return PROFILE;
  return null;
};

function platformOf(host: string): SocialPlatform | null {
  const h = host.replace(/^(www|m|mobile|music)\./, "");
  if (h === "tiktok.com" || h.endsWith(".tiktok.com")) return "tiktok";
  if (h === "instagram.com" || h === "instagr.am") return "instagram";
  if (h === "x.com" || h === "twitter.com") return "x";
  if (h === "youtube.com" || h === "youtu.be") return "youtube";
  if (h === "facebook.com" || h === "fb.com" || h === "fb.watch") return "facebook";
  if (h === "threads.net" || h === "threads.com") return "threads";
  if (h === "pin.it" || /^pinterest\.[a-z.]+$/.test(h) || /^[a-z]{2}\.pinterest\.[a-z.]+$/.test(h)) return "pinterest";
  if (h === "linkedin.com") return "linkedin";
  return null;
}

const RULES: Readonly<Record<SocialPlatform, Rule>> = {
  tiktok,
  instagram,
  x,
  youtube,
  facebook,
  threads,
  pinterest,
  linkedin,
};

function socialLabel(platform: SocialPlatform, kind: LinkKindId, segs: readonly string[]): string {
  const name = PLATFORM_NAMES[platform];
  if (kind === POST) {
    if (platform === "youtube") return first(segs) === "shorts" ? "YouTube Short detected" : "YouTube video detected";
    if (platform === "pinterest") return "Pinterest pin detected";
    return `${name} post detected`;
  }
  if (platform === "youtube") return "YouTube channel detected";
  if (platform === "facebook" || platform === "linkedin") {
    return first(segs) === "company" ? `${name} page detected` : `${name} profile detected`;
  }
  return `${name} profile detected`;
}

/** Classify an absolute http(s) URL. Unknown or unparsable input is a website. */
export function detectLinkKind(raw: string): LinkKind {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { kind: "website", platform: null, label: "Website detected" };
  }
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  const bare = host.replace(/^www\./, "");
  if (bare === "apps.apple.com" || bare === "itunes.apple.com") {
    return { kind: "app_store", platform: null, label: "App Store app detected" };
  }
  if (bare === "play.google.com") {
    return { kind: "play_store", platform: null, label: "Google Play app detected" };
  }
  const platform = platformOf(host);
  const segs = url.pathname.split("/").filter(Boolean);
  const kind = platform ? RULES[platform](host.replace(/^www\./, ""), segs, url) : null;
  if (!platform || !kind) return { kind: "website", platform: null, label: "Website detected" };
  return { kind, platform, label: socialLabel(platform, kind, segs) };
}
