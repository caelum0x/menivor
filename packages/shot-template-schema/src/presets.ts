/**
 * Seed genre presets + registry (mirror of `presets.py`).
 *
 * Each preset is the **blueprint projection** of a system template seeded by the
 * backend `templates` domain (`apps/api/app/domains/templates/presets/`): same
 * slug, genre, aspect, and slot role-sequence, with each slot's fractional timing
 * expanded against the template's `default_duration_s` into the integer-ms slots
 * pinned here. The frontends render these in the `/blueprints` picker; the backend
 * enforces at registry load that every seeded template projects **exactly** onto
 * the preset here (byte-identical `contentHash`) — so the picker and the seeded
 * templates cannot drift out of sync. One definition, no drift.
 */

import { makeSlot, makeTemplate, type ShotTemplate } from "./template.js";

const PRESETS: Record<string, ShotTemplate> = {
  "product-demo-ad": makeTemplate("product-demo-ad", "marketing", "9:16", [
    makeSlot("hook", 0, 3600, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("setup", 3600, 9000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("rising", 9000, 21600, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("payoff", 21600, 26400, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("cta", 26400, 30000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
  ]),
  "testimonial-ad": makeTemplate("testimonial-ad", "marketing", "9:16", [
    makeSlot("hook", 0, 3500, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("setup", 3500, 10000, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("payoff", 10000, 20500, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("cta", 20500, 25000, { caption_preset: "clean_white", transition_out: "cut" }),
  ]),
  "before-after": makeTemplate("before-after", "marketing", "9:16", [
    makeSlot("hook", 0, 3500, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("setup", 3500, 9500, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("rising", 9500, 18500, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("climax", 18500, 22500, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("cta", 22500, 25000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
  ]),
  "listicle": makeTemplate("listicle", "edutainment", "9:16", [
    makeSlot("hook", 0, 2800, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("rising", 2800, 21840, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("payoff", 21840, 25200, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("cta", 25200, 28000, { caption_preset: "bold_violet", transition_out: "cut" }),
  ]),
  "greenscreen-react": makeTemplate("greenscreen-react", "commentary", "9:16", [
    makeSlot("hook", 0, 3900, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("body", 3900, 18600, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("payoff", 18600, 25800, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("cta", 25800, 30000, { caption_preset: "clean_white", transition_out: "cut" }),
  ]),
  "minecraft-reddit-split": makeTemplate("minecraft-reddit-split", "brainrot-split", "9:16", [
    makeSlot("hook", 0, 2025, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("setup", 2025, 9900, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("rising", 9900, 31500, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("climax", 31500, 39600, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("cta", 39600, 45000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
  ]),
  "quiz-engagement": makeTemplate("quiz-engagement", "engagement", "9:16", [
    makeSlot("hook", 0, 2200, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("rising", 2200, 15400, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("climax", 15400, 18920, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("cta", 18920, 20900, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("loop", 20900, 22000, { caption_preset: "karaoke_green", transition_out: "cut" }),
  ]),
  "split-screen-gameplay-story": makeTemplate("split-screen-gameplay-story", "brainrot-split", "9:16", [
    makeSlot("hook", 0, 2250, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("body", 2250, 40500, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("cta", 40500, 45000, { caption_preset: "karaoke_green", transition_out: "cut" }),
  ]),
  "movie-recap": makeTemplate("movie-recap", "recap", "9:16", [
    makeSlot("hook", 0, 4800, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("setup", 4800, 15000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("body", 15000, 49200, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("payoff", 49200, 56400, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("cta", 56400, 60000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
  ]),
  "fake-ai-podcast": makeTemplate("fake-ai-podcast", "podcast", "9:16", [
    makeSlot("hook", 0, 3000, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("exchange", 3000, 45000, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("button", 45000, 50000, { caption_preset: "bold_violet", transition_out: "cut" }),
  ]),
  "asmr-satisfying-loop": makeTemplate("asmr-satisfying-loop", "asmr", "9:16", [
    makeSlot("hook", 0, 1000, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("body", 1000, 4500, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("seam", 4500, 5000, { caption_preset: "clean_white", transition_out: "cut" }),
  ]),
  "anime-beat-edit": makeTemplate("anime-beat-edit", "edit", "9:16", [
    makeSlot("hook", 0, 1600, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("body", 1600, 18400, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("payoff", 18400, 20000, { caption_preset: "clean_white", transition_out: "cut" }),
  ]),
  "brainrot-ai-meme": makeTemplate("brainrot-ai-meme", "meme", "9:16", [
    makeSlot("hook", 0, 1440, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("escalation", 1440, 9000, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("payoff", 9000, 12000, { caption_preset: "bold_violet", transition_out: "cut" }),
  ]),
  "platform-hook-open": makeTemplate("platform-hook-open", "opener", "9:16", [
    makeSlot("hook", 0, 500, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("setup", 500, 3000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("payoff", 3000, 5000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
  ]),
  "talking-head-explainer": makeTemplate("talking-head-explainer", "talking-head", "9:16", [
    makeSlot("hook", 0, 4000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("setup", 4000, 10000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("body", 10000, 32800, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("payoff", 32800, 36800, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("cta", 36800, 40000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
  ]),
  "faceless-facts": makeTemplate("faceless-facts", "faceless", "9:16", [
    makeSlot("hook", 0, 3060, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("rising", 3060, 27200, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("payoff", 27200, 30600, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("cta", 30600, 34000, { caption_preset: "bold_violet", transition_out: "cut" }),
  ]),
  "tutorial-howto": makeTemplate("tutorial-howto", "tutorial", "9:16", [
    makeSlot("hook", 0, 4000, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("setup", 4000, 10000, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("rising", 10000, 42500, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("payoff", 42500, 46500, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("cta", 46500, 50000, { caption_preset: "karaoke_green", transition_out: "cut" }),
  ]),
  "news-brief": makeTemplate("news-brief", "news", "9:16", [
    makeSlot("hook", 0, 3500, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("setup", 3500, 9800, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("body", 9800, 28000, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("payoff", 28000, 32200, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("cta", 32200, 35000, { caption_preset: "clean_white", transition_out: "cut" }),
  ]),
  "story-time": makeTemplate("story-time", "story", "9:16", [
    makeSlot("hook", 0, 3600, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("setup", 3600, 11250, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("rising", 11250, 27000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("climax", 27000, 36000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("payoff", 36000, 41400, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("cta", 41400, 45000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
  ]),
  "quote-motivation": makeTemplate("quote-motivation", "motivation", "9:16", [
    makeSlot("hook", 0, 3300, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("rising", 3300, 14960, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("climax", 14960, 19360, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("cta", 19360, 22000, { caption_preset: "clean_white", transition_out: "cut" }),
  ]),
  "countdown-ranking": makeTemplate("countdown-ranking", "ranking", "9:16", [
    makeSlot("hook", 0, 3300, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("rising", 3300, 23760, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("climax", 23760, 29040, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("cta", 29040, 33000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
  ]),
  "recipe-quick": makeTemplate("recipe-quick", "food", "9:16", [
    makeSlot("hook", 0, 3000, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("setup", 3000, 7200, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("rising", 7200, 24600, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("payoff", 24600, 27600, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("cta", 27600, 30000, { caption_preset: "bold_violet", transition_out: "cut" }),
  ]),
  "get-ready-with-me": makeTemplate("get-ready-with-me", "lifestyle", "9:16", [
    makeSlot("hook", 0, 3600, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("setup", 3600, 10000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("body", 10000, 34000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
    makeSlot("cta", 34000, 40000, { caption_preset: "karaoke_yellow", transition_out: "cut" }),
  ]),
  "day-in-the-life": makeTemplate("day-in-the-life", "vlog", "9:16", [
    makeSlot("hook", 0, 3600, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("setup", 3600, 9900, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("body", 9900, 38700, { caption_preset: "clean_white", transition_out: "cut" }),
    makeSlot("cta", 38700, 45000, { caption_preset: "clean_white", transition_out: "cut" }),
  ]),
  "street-interview": makeTemplate("street-interview", "interview", "9:16", [
    makeSlot("hook", 0, 3800, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("rising", 3800, 30400, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("climax", 30400, 34200, { caption_preset: "karaoke_green", transition_out: "cut" }),
    makeSlot("cta", 34200, 38000, { caption_preset: "karaoke_green", transition_out: "cut" }),
  ]),
  "meme-explainer": makeTemplate("meme-explainer", "explainer", "9:16", [
    makeSlot("hook", 0, 2600, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("setup", 2600, 7280, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("body", 7280, 19500, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("payoff", 19500, 23400, { caption_preset: "bold_violet", transition_out: "cut" }),
    makeSlot("cta", 23400, 26000, { caption_preset: "bold_violet", transition_out: "cut" }),
  ]),
};

export function getPreset(slug: string): ShotTemplate {
  const t = PRESETS[slug];
  if (!t) throw new Error(`unknown template preset ${slug}`);
  return t;
}

export function listPresets(genre?: string): string[] {
  return Object.keys(PRESETS)
    .filter((s) => genre === undefined || PRESETS[s].genre === genre)
    .sort();
}
