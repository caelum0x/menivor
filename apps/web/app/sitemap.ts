import type { MetadataRoute } from "next";
import { buildSitemapEntries } from "@/lib/seo";

/**
 * Sitemap (Next.js App Router). Enumerates every public, indexable marketing
 * route: the landing page, pricing, the editor, the tools/features/guides hub
 * pages, and every programmatically generated page. The URL list is derived
 * from the SEO data module (`@/lib/seo`), so adding a use case or guide extends the
 * sitemap automatically. Authenticated app surfaces are intentionally excluded.
 */
// Computed once at module load (one per deployment), not per request — a
// `lastmod` that changes on every crawl is indistinguishable from no
// `lastmod` at all, so Google ignores it (SEO audit, 2026-10-19). This still
// isn't a true per-page content date, but it now only moves when the site
// actually redeploys, which is the signal lastmod is supposed to carry.
const DEPLOY_TIME = new Date();

export default function sitemap(): MetadataRoute.Sitemap {
  return buildSitemapEntries(DEPLOY_TIME);
}
