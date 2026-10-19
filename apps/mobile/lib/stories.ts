/**
 * Typed client + presentation helpers for the REDDIT STORY ingest engine —
 * the Reddit-thread → story-reel source (`POST /stories/reddit`).
 *
 * This is a sibling of the URL ingest path in {@link module:lib/repurpose}: it
 * is stateless (no job is created here). The backend fetches the Reddit thread,
 * narrates it, and returns a template-bound reel draft (the flagship
 * `minecraft-reddit-split` split preset over the looping minecraft-parkour
 * background) which the screen previews so the creator can confirm the hook +
 * script before spending credits, then submit it from Create.
 *
 * The wire transport (auth via `x-api-key`, JSON envelope unwrapping, typed
 * errors) is the shared api client; this module only adds the typed request
 * function and side-effect-free domain helpers the screen layers on top.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

// ---------------------------------------------------------------------------
// Wire types (mirror app/domains/stories/router.py + parse.py)
// ---------------------------------------------------------------------------

/** An immutable, cleaned Reddit thread ready for narration (`RedditThread`). */
export interface RedditThread {
  readonly title: string;
  readonly subreddit: string;
  readonly author: string;
  readonly body: string;
  readonly top_comments: readonly string[];
}

/**
 * The template-bound reel draft returned for a story (a `JobCreateRequest`-shaped
 * flat dict). The known editorial fields are typed; unknown keys ride through so
 * the preview never drops server-added fields (character sidecar, effects, …).
 */
export interface StoryReelDraft {
  readonly video_subject?: string;
  readonly video_script?: string;
  readonly layout?: string;
  readonly caption_style?: string;
  readonly camera_motion?: string;
  readonly music_prompt?: string;
  readonly background_id?: string;
  readonly aspect?: string;
  readonly voice_name?: string;
  readonly [key: string]: unknown;
}

/** Result of `POST /stories/reddit` — never persisted (stateless). */
export interface RedditStoryResult {
  readonly url: string;
  readonly thread: RedditThread;
  readonly reel_draft: StoryReelDraft;
}

/** Body for `POST /stories/reddit`. Only `url` is required. */
export interface CreateRedditStoryBody {
  readonly url: string;
  /** Override the reel subject/title (defaults to the thread title). */
  readonly subject?: string;
  /** ElevenLabs narration voice id (folds into `elevenlabs:<id>`). */
  readonly voice_id?: string;
}

/**
 * POST /stories/reddit — turn a Reddit thread URL into a submittable story-reel
 * draft. Authenticated but stateless: no job is created, the caller submits the
 * returned draft to the reel-create path.
 */
export function createRedditStory(
  body: CreateRedditStoryBody,
  options?: RequestOptions,
): Promise<RedditStoryResult> {
  const payload: CreateRedditStoryBody = {
    url: body.url,
    ...(body.subject ? { subject: body.subject } : {}),
    ...(body.voice_id ? { voice_id: body.voice_id } : {}),
  };
  return request<RedditStoryResult>("/stories/reddit", {
    method: "POST",
    body: payload,
    options,
  });
}

// ---------------------------------------------------------------------------
// Pure presentation / validation helpers (side-effect free)
// ---------------------------------------------------------------------------

/** Whether a value is a plausible http(s) URL. */
export function looksLikeUrl(value: string): boolean {
  const v = value.trim().toLowerCase();
  return v.startsWith("http://") || v.startsWith("https://");
}

/**
 * Whether a value looks like a Reddit thread URL (reddit.com / redd.it host,
 * over http(s)). Kept permissive — the backend does the authoritative fetch and
 * surfaces a clean error for anything it cannot read.
 */
export function looksLikeRedditUrl(value: string): boolean {
  const v = value.trim().toLowerCase();
  if (!looksLikeUrl(v)) return false;
  return (
    v.includes("reddit.com/") ||
    v.includes("redd.it/") ||
    v.includes("//reddit.com") ||
    v.includes(".reddit.com/")
  );
}

/** A readable subject/title for a story draft, falling back to the thread. */
export function storyDraftSubject(result: RedditStoryResult): string {
  const subject = (result.reel_draft.video_subject ?? "").trim();
  if (subject) return subject;
  const title = (result.thread.title ?? "").trim();
  if (title) return title;
  return "Reddit story";
}

/** A compact "r/subreddit · u/author" attribution line (blank when absent). */
export function threadAttribution(thread: RedditThread): string {
  const parts: string[] = [];
  const sub = (thread.subreddit ?? "").trim();
  const author = (thread.author ?? "").trim();
  if (sub) parts.push(`r/${sub}`);
  if (author) parts.push(`u/${author}`);
  return parts.join(" · ");
}

/** Rough word count of the narratable story body (0 when empty). */
export function bodyWordCount(body: string): number {
  const trimmed = (body ?? "").trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).length;
}

/** The narration script the pipeline will read, if the draft carries one. */
export function draftScript(draft: StoryReelDraft): string {
  return (draft.video_script ?? "").trim();
}
