/**
 * Unified media gateway contract — OpenRouter-style `/images` + `/videos` +
 * `/audio`. Stable client-facing shapes shared by the TypeScript/Python SDKs and
 * every first-party surface, plus the canonical endpoint paths. The OpenAPI
 * artifact (`openapi/reelforge-v1.json`) is the machine source of truth; this
 * module is the hand-curated, ergonomic mirror clients import.
 */
/** Canonical media-gateway endpoint paths (relative to the `/api/v1` base).
 *  Namespaced under `/media` so they never collide with MPT's legacy routes. */
export const MEDIA_GATEWAY_PATHS = {
    models: "/media/models",
    images: "/media/images",
    videos: "/media/videos",
    video: (id) => `/media/videos/${encodeURIComponent(id)}`,
    audio: "/media/audio",
    audioJob: (id) => `/media/audio/${encodeURIComponent(id)}`,
    credits: "/media/credits",
    usage: "/media/usage",
    generations: "/media/generations",
    generation: (id) => `/media/generation/${encodeURIComponent(id)}`,
    identities: "/media/identities",
    provenance: (id) => `/media/generation/${encodeURIComponent(id)}/provenance`,
    evidence: (id) => `/media/generation/${encodeURIComponent(id)}/evidence`,
};
/** Terminal statuses for a media job (video/audio). */
export const MEDIA_TERMINAL_STATUSES = ["completed", "failed"];
export function isMediaJobTerminal(status) {
    return MEDIA_TERMINAL_STATUSES.includes(status);
}
