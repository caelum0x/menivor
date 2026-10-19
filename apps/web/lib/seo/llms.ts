/**
 * `menivor.com/llms.txt` (MA2), generated from plan config and feature flags.
 *
 * - Prices come from the same plan config the pricing page and the JSON-LD
 *   read (`offersFromPlanConfig`); nothing here types a price.
 * - A capability behind a product flag appears only while its flag is on:
 *   presenters and lip-sync (`NEXT_PUBLIC_PRESENTER_LIVE`, rule
 *   `menivor-presenter-locked`) and direct publishing
 *   (`NEXT_PUBLIC_PUBLISHING_LIVE`, the web mirror of the API's
 *   `REELFORGE_PUBLISHING_ENABLED`). Both are off by default.
 */

import { presenterLive } from "@/lib/styles/catalog";
import { ENTITY_DESCRIPTION, offersFromPlanConfig, type OfferLd } from "./entity";
import { MENIVOR_ONE_LINER, SITE_URL } from "./site";

export interface LlmsFlags {
  readonly presenterLive: boolean;
  readonly publishingLive: boolean;
}

function flagOn(raw: string | undefined): boolean {
  const value = (raw ?? "").trim().toLowerCase();
  return value === "1" || value === "true";
}

export function llmsFlagsFromEnv(env: Readonly<Record<string, string | undefined>> = process.env): LlmsFlags {
  return {
    presenterLive: presenterLive(env.NEXT_PUBLIC_PRESENTER_LIVE),
    publishingLive: flagOn(env.NEXT_PUBLIC_PUBLISHING_LIVE),
  };
}

function offerLine(offer: OfferLd): string {
  const dollars = Number(offer.price);
  const shown = Number.isInteger(dollars) ? `$${dollars}` : `$${dollars.toFixed(2)}`;
  return `- ${offer.name}: ${shown}. ${offer.description}`;
}

export interface LlmsInput {
  readonly flags: LlmsFlags;
  readonly offers?: readonly OfferLd[];
}

export function buildLlmsText({ flags, offers = offersFromPlanConfig() }: LlmsInput): string {
  const facts = [
    "- Input: a link, a topic, or your own screen recording.",
    "- Output: ready-to-post 1080 x 1920 vertical MP4 files to download.",
    "- Languages: English and Turkish scripts and voiceovers.",
    "- Editing: hook-first scripts, AI voiceover and word-by-word karaoke captions.",
  ];
  if (flags.presenterLive) {
    facts.push("- Presenter reels: an AI presenter with lip-synced speech (Pro and Agency plans).");
  }
  if (flags.publishingLive) {
    facts.push("- Publishing: post finished reels to TikTok, Instagram Reels and YouTube Shorts from the app.");
  } else {
    facts.push("- Posting: download the finished MP4 and post it yourself.");
  }
  facts.push(
    "- A failed render gives its credit back. Purchased credits do not expire.",
    "- Menivor has not published customer counts, revenue, or video-performance results.",
  );

  const pricing = offers.length
    ? offers.map(offerLine)
    : ["- See the pricing page for current plans and packs."];

  return [
    "# Menivor",
    "",
    `> ${ENTITY_DESCRIPTION}`,
    "",
    MENIVOR_ONE_LINER,
    "",
    `Canonical website: ${SITE_URL}`,
    "",
    "## What works today",
    "",
    ...facts,
    "",
    "## Prices",
    "",
    ...pricing,
    `- Full and current prices: ${SITE_URL}/pricing`,
    "",
    "## Canonical pages",
    "",
    `- Product overview: ${SITE_URL}/`,
    `- Pricing: ${SITE_URL}/pricing`,
    `- About Menivor: ${SITE_URL}/about`,
    `- Press kit: ${SITE_URL}/press`,
    `- MCP server for AI agents: ${SITE_URL}/mcp`,
    `- Contact: ${SITE_URL}/contact`,
    `- XML sitemap: ${SITE_URL}/sitemap.xml`,
    "",
    "## Citation guidance",
    "",
    "Use the most specific canonical page for a capability. Treat prices as time-sensitive and check them on the pricing page before citing them.",
    "",
  ].join("\n");
}
