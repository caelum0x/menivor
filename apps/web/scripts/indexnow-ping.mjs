#!/usr/bin/env node
/**
 * IndexNow ping for menivor.com (Bing, Yandex, Seznam, Naver and other
 * IndexNow engines share submissions).
 *
 * Fetches the live sitemap (follows a sitemap index if one is served), then
 * POSTs every URL on the canonical host to https://api.indexnow.org/indexnow.
 * The key file must already be live at https://menivor.com/<key>.txt, so run
 * this only after a deploy that includes apps/web/public/<key>.txt.
 *
 * Usage (from the repo root):
 *   node apps/web/scripts/indexnow-ping.mjs            # submit
 *   node apps/web/scripts/indexnow-ping.mjs --dry-run  # list URLs only
 *
 * Optional env: INDEXNOW_SITE (default https://menivor.com),
 * INDEXNOW_KEY (default the key below). No dependencies; Node 18+.
 */

const SITE = (process.env.INDEXNOW_SITE || "https://menivor.com").replace(/\/+$/, "");
const KEY = process.env.INDEXNOW_KEY || "c191352378636a190388f3bd14b7fb16";
const ENDPOINT = "https://api.indexnow.org/indexnow";
/** IndexNow accepts up to 10,000 URLs per request. */
const BATCH_SIZE = 10_000;
const MAX_SITEMAPS = 50;
const DRY_RUN = process.argv.includes("--dry-run");

function locs(xml) {
  return [...xml.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/gi)].map((m) =>
    m[1].replace(/&amp;/g, "&"),
  );
}

async function fetchText(url) {
  const res = await fetch(url, { headers: { "user-agent": "menivor-indexnow-ping" } });
  if (!res.ok) throw new Error(`GET ${url} failed: HTTP ${res.status}`);
  return res.text();
}

/** Collect page URLs, following <sitemapindex> entries breadth-first. */
async function collectUrls(rootSitemap) {
  const queue = [rootSitemap];
  const seenSitemaps = new Set();
  const urls = new Set();
  while (queue.length > 0 && seenSitemaps.size < MAX_SITEMAPS) {
    const sitemapUrl = queue.shift();
    if (seenSitemaps.has(sitemapUrl)) continue;
    seenSitemaps.add(sitemapUrl);
    const xml = await fetchText(sitemapUrl);
    const entries = locs(xml);
    if (/<sitemapindex[\s>]/i.test(xml)) queue.push(...entries);
    else entries.forEach((u) => urls.add(u));
  }
  return [...urls];
}

async function submit(urlList) {
  const host = new URL(SITE).host;
  const res = await fetch(ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({
      host,
      key: KEY,
      keyLocation: `${SITE}/${KEY}.txt`,
      urlList,
    }),
  });
  const body = await res.text().catch(() => "");
  // 200 = accepted, 202 = accepted, key validation pending.
  if (res.status !== 200 && res.status !== 202) {
    throw new Error(`IndexNow POST failed: HTTP ${res.status} ${body.slice(0, 300)}`);
  }
  return res.status;
}

async function main() {
  const host = new URL(SITE).host;
  const all = await collectUrls(`${SITE}/sitemap.xml`);
  const urls = all.filter((u) => {
    try {
      return new URL(u).host === host;
    } catch {
      return false;
    }
  });
  const skipped = all.length - urls.length;
  console.log(`Found ${urls.length} URLs on ${host}${skipped ? ` (${skipped} off-host skipped)` : ""}.`);
  if (urls.length === 0) throw new Error("No URLs found in the sitemap; nothing to submit.");

  if (DRY_RUN) {
    urls.forEach((u) => console.log(u));
    return;
  }

  const keyRes = await fetch(`${SITE}/${KEY}.txt`);
  const keyBody = keyRes.ok ? (await keyRes.text()).trim() : "";
  if (keyBody !== KEY) {
    throw new Error(`Key file ${SITE}/${KEY}.txt is not live (HTTP ${keyRes.status}); deploy it first.`);
  }

  for (let i = 0; i < urls.length; i += BATCH_SIZE) {
    const batch = urls.slice(i, i + BATCH_SIZE);
    const status = await submit(batch);
    console.log(`Submitted ${batch.length} URLs: HTTP ${status}`);
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
