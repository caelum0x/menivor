/**
 * X web-intent composer URL. No X API, no sign-in, no upload: the browser
 * opens https://x.com/intent/post with a prefilled hook, optional hashtags,
 * and the product link. Length uses twitter-text (URLs weigh 23).
 */

import twitterText from "twitter-text";

/** Public composer. `text` and `url` are the only parameters we set. */
export const X_INTENT_ENDPOINT = "https://x.com/intent/post";

/** X's weighted character limit (twitter-text config v3). */
export const X_WEIGHTED_LIMIT = 280;

const ELLIPSIS = "…";

export interface XShareInput {
  /** Chosen hook. Used when it is non-empty. */
  readonly hook?: string | null;
  /** Generated hooks, in order. The first non-empty one is the fallback. */
  readonly hooks?: readonly (string | null | undefined)[];
  /** Optional tags, with or without a leading `#`. Invalid tags are dropped. */
  readonly hashtags?: readonly (string | null | undefined)[];
  /** Product or page link the reel was made from. Only http(s) is kept. */
  readonly sourceUrl?: string | null;
}

export interface XIntent {
  /** Absolute intent URL, UTF-8 percent-encoded. */
  readonly href: string;
  /** Prefilled `text` (hook plus any hashtags that fit). Never includes the URL. */
  readonly text: string;
  /** Prefilled `url`, or "" when there is no http(s) source link. */
  readonly url: string;
  /** twitter-text weighted length of the post X will compose (`text` + `url`). */
  readonly weightedLength: number;
}

/** The post body X assembles: the text, then the source link separated by a space. */
export function composedShareTweet(text: string, url: string): string {
  if (text && url) return `${text} ${url}`;
  return text || url;
}

/** Chosen hook when one was picked, otherwise the first generated hook. */
export function chooseShareHook(input: {
  readonly chosen?: string | null;
  readonly hooks?: readonly (string | null | undefined)[];
}): string {
  const chosen = cleanHook(input.chosen ?? "");
  if (chosen) return chosen;
  for (const hook of input.hooks ?? []) {
    const text = cleanHook(hook ?? "");
    if (text) return text;
  }
  return "";
}

/** Build the intent URL, truncating the hook so the post stays within 280. */
export function buildXIntent(input: XShareInput): XIntent {
  const hook = chooseShareHook({ chosen: input.hook, hooks: input.hooks });
  const url = normalizeHttpUrl(input.sourceUrl);
  let tags = normalizeHashtags(input.hashtags);

  let hookText = "";
  let tagsLine = "";
  while (tags.length > 0) {
    tagsLine = tags.map((tag) => `#${tag}`).join(" ");
    hookText = truncateHook(hook, tagsLine, url);
    if (hook && !hookText) {
      tags = tags.slice(0, -1);
      continue;
    }
    if (fits(composed(hookText, tagsLine, url))) break;
    tags = tags.slice(0, -1);
  }
  if (tags.length === 0) {
    tagsLine = "";
    hookText = truncateHook(hook, "", url);
  }

  const text = joinBody(hookText, tagsLine);
  const full = composedShareTweet(text, url);
  return {
    href: buildHref(text, url),
    text,
    url,
    weightedLength: full ? twitterText.parseTweet(full).weightedLength : 0,
  };
}

function cleanHook(raw: string): string {
  return raw
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function normalizeHttpUrl(raw: string | null | undefined): string {
  const text = (raw ?? "").trim();
  if (!text) return "";
  try {
    const url = new URL(text);
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    if (!url.hostname) return "";
    return url.toString();
  } catch {
    return "";
  }
}

function normalizeHashtags(raw: readonly (string | null | undefined)[] | undefined): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of raw ?? []) {
    const trimmed = (item ?? "").trim();
    if (!trimmed || /\s/u.test(trimmed)) continue;
    const withHash = trimmed.startsWith("#") ? trimmed : `#${trimmed}`;
    if (!twitterText.isValidHashtag(withHash)) continue;
    const tag = withHash.slice(1);
    const key = tag.toLocaleLowerCase();
    if (!tag || seen.has(key)) continue;
    seen.add(key);
    out.push(tag);
  }
  return out;
}

function joinBody(hook: string, tagsLine: string): string {
  if (hook && tagsLine) return `${hook}\n\n${tagsLine}`;
  return hook || tagsLine;
}

function composed(hook: string, tagsLine: string, url: string): string {
  return composedShareTweet(joinBody(hook, tagsLine), url);
}

function fits(text: string): boolean {
  if (!text) return true;
  const result = twitterText.parseTweet(text);
  return result.valid && result.weightedLength <= X_WEIGHTED_LIMIT;
}

/**
 * Shorten `hook` until hook + hashtags + url fit. Cuts on a space when the
 * limit lands mid-word, and marks a shortened hook with an ellipsis.
 */
function truncateHook(hook: string, tagsLine: string, url: string): string {
  if (!hook) return "";
  if (fits(composed(hook, tagsLine, url))) return hook;

  const chars = Array.from(hook);
  let lo = 0;
  let hi = chars.length;
  let best = 0;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const prefix = chars.slice(0, mid).join("").replace(/\s+$/u, "");
    const candidate = prefix ? `${prefix}${ELLIPSIS}` : "";
    if (candidate && fits(composed(candidate, tagsLine, url))) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  let prefix = chars.slice(0, best).join("").replace(/\s+$/u, "");
  const next = hook.slice(prefix.length, prefix.length + 1);
  if (next && !/\s/u.test(next)) {
    const space = prefix.lastIndexOf(" ");
    if (space > 0) {
      const snapped = prefix.slice(0, space).replace(/\s+$/u, "");
      if (snapped && fits(composed(`${snapped}${ELLIPSIS}`, tagsLine, url))) {
        prefix = snapped;
      }
    }
  }
  if (!prefix || prefix === hook) return prefix;
  return `${prefix}${ELLIPSIS}`;
}

function buildHref(text: string, url: string): string {
  const parts: string[] = [];
  if (text) parts.push(`text=${encodeURIComponent(text)}`);
  if (url) parts.push(`url=${encodeURIComponent(url)}`);
  if (parts.length === 0) return X_INTENT_ENDPOINT;
  return `${X_INTENT_ENDPOINT}?${parts.join("&")}`;
}
