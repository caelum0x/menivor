/**
 * Megaphone feed: the weekly "Made with Menivor" videos we make for our own
 * products (apps/api/app/domains/megaphone). Published as JSON at
 * media.menivor.com/megaphone/manifest.json; this module fetches it, keeps
 * only well-formed entries, and builds VideoObject JSON-LD and the video
 * sitemap. Every failure degrades to an empty list, never a broken page.
 */

export const MANIFEST_URL = "https://media.menivor.com/megaphone/manifest.json";
export const SITE_URL = "https://menivor.com";
export const GALLERY_PATH = "/made-with-menivor";
const MEDIA_ORIGIN = "https://media.menivor.com/";
const FETCH_TIMEOUT_MS = 3000;

export type MegaphoneProduct = "bidstage" | "mail" | "oxhan" | "menivor";

export interface MegaphoneDub {
  readonly language: string;
  readonly videoUrl: string;
}

export interface MegaphoneVideo {
  readonly id: string;
  readonly product: MegaphoneProduct;
  readonly title: string;
  readonly description: string;
  readonly videoUrl: string;
  readonly posterUrl: string;
  readonly durationS: number;
  readonly width: number;
  readonly height: number;
  readonly uploadDate: string;
  readonly landingUrl: string;
  readonly language: string;
  readonly transcript: string;
  readonly dubs: readonly MegaphoneDub[];
}

export const PRODUCTS: Readonly<Record<MegaphoneProduct, { name: string; site: string; blurb: string }>> = {
  bidstage: { name: "Bidstage", site: "https://bidstage.app", blurb: "Open public tenders by country and category." },
  mail: { name: "Scribase Mail", site: "https://scribase.com/mail", blurb: "A Resend-compatible email API." },
  oxhan: { name: "Oxhan Atelier", site: "https://oxhanatelier.com", blurb: "Numbered pieces from Istanbul." },
  menivor: { name: "Menivor", site: SITE_URL, blurb: "Reels from a link or a topic." },
};

const LANDING_HOSTS = new Set(["bidstage.app", "scribase.com", "mail.scribase.com", "oxhanatelier.com", "menivor.com"]);
const ID_PATTERN = /^[a-z0-9-]{3,120}$/;

function text(value: unknown, max: number): string {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim().slice(0, max) : "";
}

function mediaUrl(value: unknown, ext: RegExp): string {
  const url = text(value, 600);
  if (!url.startsWith(MEDIA_ORIGIN) || !ext.test(url)) return "";
  try {
    return new URL(url).href;
  } catch {
    return "";
  }
}

function landingUrl(value: unknown): string {
  try {
    const url = new URL(text(value, 800));
    return url.protocol === "https:" && LANDING_HOSTS.has(url.hostname) ? url.href : "";
  } catch {
    return "";
  }
}

function isProduct(value: unknown): value is MegaphoneProduct {
  return typeof value === "string" && value in PRODUCTS;
}

/** One validated entry, or null when anything required is missing or unsafe. */
export function parseVideo(raw: unknown): MegaphoneVideo | null {
  if (!raw || typeof raw !== "object") return null;
  const v = raw as Record<string, unknown>;
  const id = text(v.id, 120);
  const videoUrl = mediaUrl(v.video_url, /\.mp4$/);
  const posterUrl = mediaUrl(v.poster_url, /\.(jpg|jpeg|png|webp)$/);
  const title = text(v.title, 140);
  const landing = landingUrl(v.landing_url);
  const uploadDate = text(v.upload_date, 40);
  const durationS = Number(v.duration_s);
  if (!ID_PATTERN.test(id) || !isProduct(v.product) || !videoUrl || !posterUrl || !title || !landing) return null;
  if (!Number.isFinite(durationS) || durationS <= 0 || durationS > 600 || Number.isNaN(Date.parse(uploadDate))) return null;
  const dubs = Array.isArray(v.dubs)
    ? v.dubs
        .map((d) => (d && typeof d === "object" ? (d as Record<string, unknown>) : {}))
        .map((d) => ({ language: text(d.language, 8), videoUrl: mediaUrl(d.video_url, /\.mp4$/) }))
        .filter((d) => /^[a-z]{2}$/.test(d.language) && d.videoUrl)
    : [];
  return {
    id,
    product: v.product,
    title,
    description: text(v.description, 400),
    videoUrl,
    posterUrl,
    durationS,
    width: Number(v.width) > 0 ? Math.round(Number(v.width)) : 1080,
    height: Number(v.height) > 0 ? Math.round(Number(v.height)) : 1920,
    uploadDate,
    landingUrl: landing,
    language: text(v.language, 8) || "en",
    transcript: text(v.transcript, 2000),
    dubs,
  };
}

export function parseFeed(raw: unknown): MegaphoneVideo[] {
  const videos = raw && typeof raw === "object" ? (raw as { videos?: unknown }).videos : undefined;
  if (!Array.isArray(videos)) return [];
  const seen = new Set<string>();
  const out: MegaphoneVideo[] = [];
  for (const item of videos.slice(0, 200)) {
    const video = parseVideo(item);
    if (video && !seen.has(video.id)) {
      seen.add(video.id);
      out.push(video);
    }
  }
  return out;
}

/** Fetch the live manifest (no caching layer on this deploy; the file is small). */
export async function loadFeed(fetchImpl: typeof fetch = fetch): Promise<MegaphoneVideo[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetchImpl(MANIFEST_URL, { signal: controller.signal, cache: "no-store" });
    if (!res.ok) return [];
    return parseFeed(await res.json());
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}

/** ISO 8601 duration ("PT31S", "PT1M5S"). */
export function isoDuration(seconds: number): string {
  const total = Math.max(1, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m ? `PT${m}M${s}S` : `PT${s}S`;
}

/** Referral link to the product with Menivor gallery attribution. */
export function productLink(video: MegaphoneVideo): string {
  const url = new URL(video.landingUrl);
  url.searchParams.set("utm_source", "menivor");
  url.searchParams.set("utm_medium", "referral");
  url.searchParams.set("utm_campaign", "made-with-menivor");
  url.searchParams.set("utm_content", video.id);
  return url.href;
}

export function videoObject(video: MegaphoneVideo, pageUrl: string): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "VideoObject",
    name: video.title,
    description: video.description || video.title,
    thumbnailUrl: [video.posterUrl],
    uploadDate: video.uploadDate,
    duration: isoDuration(video.durationS),
    contentUrl: video.videoUrl,
    embedUrl: pageUrl,
    inLanguage: video.language,
    ...(video.transcript ? { transcript: video.transcript } : {}),
    creator: { "@type": "Organization", name: "Menivor", url: SITE_URL },
  };
}

/** JSON for a <script type="application/ld+json"> body, safe against "</script>". */
export function jsonLdText(data: unknown): string {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function xml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/** Google video sitemap: every video sits on the gallery page. */
export function videoSitemapXml(videos: readonly MegaphoneVideo[], pageUrl = `${SITE_URL}${GALLERY_PATH}`): string {
  const entries = videos
    .map(
      (v) =>
        "    <video:video>\n" +
        `      <video:thumbnail_loc>${xml(v.posterUrl)}</video:thumbnail_loc>\n` +
        `      <video:title>${xml(v.title)}</video:title>\n` +
        `      <video:description>${xml((v.description || v.title).slice(0, 2048))}</video:description>\n` +
        `      <video:content_loc>${xml(v.videoUrl)}</video:content_loc>\n` +
        `      <video:duration>${Math.max(1, Math.round(v.durationS))}</video:duration>\n` +
        `      <video:publication_date>${xml(v.uploadDate)}</video:publication_date>\n` +
        "    </video:video>\n",
    )
    .join("");
  return (
    '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">\n' +
    `  <url>\n    <loc>${xml(pageUrl)}</loc>\n${entries}  </url>\n` +
    "</urlset>\n"
  );
}
