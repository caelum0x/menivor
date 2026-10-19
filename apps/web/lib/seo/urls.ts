/**
 * Enumerates every public, indexable URL the programmatic SEO engine produces,
 * with sitemap metadata. Consumed by `app/sitemap.ts`. Keeping this here (next
 * to the data) means adding a use case, feature, or guide page
 * automatically extends the sitemap — no separate list to maintain.
 */

import type { MetadataRoute } from "next";
import { SITE_URL } from "./site";
import { USE_CASE_SLUGS } from "./usecases";
import { FEATURE_SLUGS } from "./features";
import { PROVIDER_SLUGS } from "./providers";
import { GUIDE_SLUGS } from "./guides";
import { PLATFORM_SLUGS } from "./platforms";
import { MAKE_TYPE_SLUGS } from "./make";
import { INDEXABLE_VERTICAL_SLUGS } from "./verticals";
import { FREE_TOOL_SLUGS } from "./free-tools/catalog";

type ChangeFrequency = MetadataRoute.Sitemap[number]["changeFrequency"];

interface SeoRouteGroup {
  readonly path: (slug: string) => string;
  readonly slugs: readonly string[];
  readonly priority: number;
  readonly changeFrequency: ChangeFrequency;
}

/** Static (non-templated) marketing routes, including the hub/index pages. */
const STATIC_ROUTES: ReadonlyArray<{
  readonly path: string;
  readonly priority: number;
  readonly changeFrequency: ChangeFrequency;
}> = [
  { path: "/", priority: 1, changeFrequency: "weekly" },
  { path: "/pricing", priority: 0.8, changeFrequency: "monthly" },
  { path: "/styles", priority: 0.8, changeFrequency: "weekly" },
  { path: "/editor", priority: 0.8, changeFrequency: "weekly" },
  { path: "/mcp", priority: 0.7, changeFrequency: "monthly" },
  { path: "/integrations", priority: 0.7, changeFrequency: "monthly" },
  { path: "/tools", priority: 0.7, changeFrequency: "weekly" },
  { path: "/tools/app-store-audit", priority: 0.8, changeFrequency: "weekly" },
  { path: "/tools/aso-keyword-checker", priority: 0.7, changeFrequency: "weekly" },
  { path: "/features", priority: 0.7, changeFrequency: "weekly" },
  { path: "/providers", priority: 0.7, changeFrequency: "weekly" },
  { path: "/creator-contract", priority: 0.5, changeFrequency: "monthly" },
  { path: "/guides", priority: 0.7, changeFrequency: "weekly" },
  { path: "/for", priority: 0.7, changeFrequency: "weekly" },
  { path: "/make", priority: 0.7, changeFrequency: "weekly" },
  { path: "/video-ads", priority: 0.8, changeFrequency: "weekly" },
  { path: "/showcase", priority: 0.6, changeFrequency: "weekly" },
  { path: "/terms", priority: 0.3, changeFrequency: "monthly" },
  { path: "/privacy", priority: 0.3, changeFrequency: "monthly" },
  { path: "/refunds", priority: 0.3, changeFrequency: "monthly" },
  { path: "/legal/acceptable-use", priority: 0.3, changeFrequency: "monthly" },
  { path: "/contact", priority: 0.4, changeFrequency: "monthly" },
  { path: "/about", priority: 0.5, changeFrequency: "monthly" },
  { path: "/press", priority: 0.4, changeFrequency: "monthly" },
];

/** Templated route groups, expanded from the data module slugs. */
const ROUTE_GROUPS: readonly SeoRouteGroup[] = [
  {
    // Free working tools (hooks, scripts, subtitles, calculators): static routes.
    path: (slug) => `/tools/${slug}`,
    slugs: FREE_TOOL_SLUGS,
    priority: 0.8,
    changeFrequency: "monthly",
  },
  {
    path: (slug) => `/tools/${slug}`,
    slugs: USE_CASE_SLUGS,
    priority: 0.6,
    changeFrequency: "monthly",
  },
  {
    path: (slug) => `/features/${slug}`,
    slugs: FEATURE_SLUGS,
    priority: 0.6,
    changeFrequency: "monthly",
  },
  {
    path: (slug) => `/providers/${slug}`,
    slugs: PROVIDER_SLUGS,
    priority: 0.6,
    changeFrequency: "monthly",
  },
  {
    path: (slug) => `/guides/${slug}`,
    slugs: GUIDE_SLUGS,
    priority: 0.6,
    changeFrequency: "monthly",
  },
  {
    path: (slug) => `/for/${slug}`,
    slugs: PLATFORM_SLUGS,
    priority: 0.7,
    changeFrequency: "monthly",
  },
  {
    path: (slug) => `/make/${slug}`,
    slugs: MAKE_TYPE_SLUGS,
    priority: 0.6,
    changeFrequency: "monthly",
  },  {
    path: (slug) => `/video-ads/${slug}`,
    slugs: INDEXABLE_VERTICAL_SLUGS,
    priority: 0.8,
    changeFrequency: "monthly",
  },
];

/** Build the full sitemap entry list (absolute URLs + metadata). */
export function buildSitemapEntries(lastModified: Date): MetadataRoute.Sitemap {
  const staticEntries: MetadataRoute.Sitemap = STATIC_ROUTES.map((route) => ({
    url: `${SITE_URL}${route.path}`,
    lastModified,
    changeFrequency: route.changeFrequency,
    priority: route.priority,
  }));

  const templatedEntries: MetadataRoute.Sitemap = ROUTE_GROUPS.flatMap((group) =>
    group.slugs.map((slug) => ({
      url: `${SITE_URL}${group.path(slug)}`,
      lastModified,
      changeFrequency: group.changeFrequency,
      priority: group.priority,
    })),
  );

  return [...staticEntries, ...templatedEntries];
}
