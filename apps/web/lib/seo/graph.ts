/**
 * Knowledge-graph projection over the SEO entity data.
 *
 * This mirrors the CalDesk / yokharita pattern: a set of typed edges computed
 * deterministically from the entity modules (competitors, use cases, features,
 * providers) — no LLM, no runtime DB. The vocabulary is closed, so the edges
 * are pure functions of the data and are stable across builds.
 *
 * Edge types:
 *   - ALTERNATIVE_TO / COMPARED_WITH : competitor ↔ competitor (same category first)
 *   - SOLVES                         : use case ↔ feature (from Feature.useCases)
 *   - HAS_FEATURE                    : competitor → feature (Feature.comparableCompetitors)
 *   - USES_PROVIDER                  : Menivor → provider, feature ↔ provider
 *   - RELATED                        : use case ↔ use case, feature ↔ feature,
 *                                      provider ↔ provider (by theme / category)
 *
 * DEAD-LINK GUARD: every internal link the site emits is built through the
 * `relatedLinksFor*` helpers here, and each candidate href is passed through
 * `pageExists()` before it is returned. An edge can therefore only ever point
 * at a slug that has a real `generateStaticParams` entry — a related link can
 * never 404.
 */

import { COMPETITORS, getCompetitor } from "./competitors";
import type { Competitor, CompetitorCategory } from "./competitors";
import { USE_CASES, USE_CASE_SLUGS, getUseCase } from "./usecases";
import type { UseCase } from "./usecases";
import { FEATURES, FEATURE_SLUGS, getFeature } from "./features";
import type { Feature } from "./features";
import { PROVIDERS, PROVIDER_SLUGS, getProvider } from "./providers";
import type { Provider } from "./providers";
import { getReelTemplate } from "./templates";
import { PLATFORM_SLUGS, getPlatform } from "./platforms";
import { MAKE_TYPE_SLUGS, getMakeType } from "./make";

/** A resolved internal link, structurally compatible with `RelatedLink`. */
export interface GraphLink {
  readonly href: string;
  readonly title: string;
  readonly description?: string;
}

/** The entity kinds that own a generated page, keyed by URL prefix. */
const SLUG_SETS: Readonly<Record<string, ReadonlySet<string>>> = {
  "/tools": new Set(USE_CASE_SLUGS),
  "/features": new Set(FEATURE_SLUGS),
  "/providers": new Set(PROVIDER_SLUGS),
  "/for": new Set(PLATFORM_SLUGS),
  "/make": new Set(MAKE_TYPE_SLUGS),
};

/**
 * DEAD-LINK GUARD. Returns true only when `href` resolves to a page that is
 * actually enumerated by a `generateStaticParams` (a `/prefix/{slug}` whose
 * slug is in the corresponding set) or is a known static hub. Everything the
 * mesh emits is filtered through this.
 */
export function pageExists(href: string): boolean {
  const STATIC_PAGES: ReadonlySet<string> = new Set([
    "/",
    "/pricing",
    "/tools",
    "/features",
    "/providers",
    "/guides",
    "/for",
    "/make",
  ]);
  if (STATIC_PAGES.has(href)) return true;

  const match = href.match(/^(\/[^/]+)\/([^/]+)$/);
  if (!match) return false;
  const prefix = match[1];
  const slug = match[2];
  if (!prefix || !slug) return false;
  const set = SLUG_SETS[prefix];
  return set?.has(slug) ?? false;
}

/** Keep only links whose href resolves to a real page, and de-duplicate. */
function guard(links: readonly GraphLink[]): GraphLink[] {
  const seen = new Set<string>();
  const out: GraphLink[] = [];
  for (const link of links) {
    if (!pageExists(link.href)) continue;
    if (seen.has(link.href)) continue;
    seen.add(link.href);
    out.push(link);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Theme maps (co-located here for the existing use-case module, which we do
// not rewrite; features/providers carry their own theme/category on the entity).
// ---------------------------------------------------------------------------

/** Thematic bucket per use case — drives RELATED use-case ↔ use-case edges. */
const USE_CASE_THEME: Readonly<Record<string, string>> = {
  "product-link-to-video": "ugc-ads",
  "tiktok-ads-from-product-page": "ugc-ads",
  "add-captions-to-video": "captions",
  "ai-ugc-ad-generator": "ugc-ads",
  "tiktok-hook-script-generator": "scripting",
  "faceless-video-generator": "faceless",
  "screen-recording-to-video": "screen-recording",
  "ai-avatar-video-generator": "avatar",
  "karaoke-caption-generator": "captions",
  "turkish-ai-video-generator": "turkish",
  "saas-demo-video-maker": "demos",
  "talking-head-video-generator": "avatar",
  "product-demo-to-reel": "demos",
  "faceless-tiktok-video-maker": "faceless",
  "faceless-youtube-shorts-maker": "faceless",
  "faceless-instagram-reels-maker": "faceless",
  "faceless-youtube-channel-videos": "faceless",
  "talking-head-tiktok-generator": "avatar",
  "ai-avatar-instagram-reels": "avatar",
  "ai-avatar-youtube-shorts": "avatar",
  "ugc-ad-for-tiktok": "ugc-ads",
  "ugc-ad-for-instagram": "ugc-ads",
  "ugc-ad-for-facebook-ads": "ugc-ads",
  "tiktok-ad-maker": "ugc-ads",
  "instagram-reels-maker": "screen-recording",
  "youtube-shorts-maker": "screen-recording",
  "explainer-video-generator": "demos",
  "product-demo-tiktok": "demos",
  "app-demo-video-maker": "demos",
  "testimonial-video-generator": "ugc-ads",
  "tutorial-video-generator": "demos",
  "how-to-video-maker": "demos",
  "listicle-video-generator": "scripting",
  "fitness-video-generator": "ugc-ads",
  "finance-video-generator": "scripting",
  "ecommerce-product-video-maker": "ugc-ads",
  "real-estate-video-maker": "demos",
  "restaurant-video-maker": "ugc-ads",
  "coach-content-video-maker": "avatar",
  "saas-marketing-video-maker": "demos",
  "course-promo-video-maker": "ugc-ads",
  "app-store-preview-video-maker": "demos",
  "shopify-product-video-maker": "ugc-ads",
  "crypto-video-generator": "scripting",
  "beauty-product-ugc-generator": "ugc-ads",
  "agency-ugc-video-generator": "ugc-ads",
  "affiliate-marketing-video-maker": "ugc-ads",
  "lead-gen-video-ad-maker": "ugc-ads",
  "product-launch-video-maker": "ugc-ads",
  "feature-announcement-video-maker": "demos",
  "onboarding-video-maker": "demos",
  "faq-video-generator": "scripting",
  "ai-spokesperson-video-generator": "avatar",
  "vertical-video-generator": "screen-recording",
  "short-form-video-generator": "scripting",
};

/**
 * Which use-case themes a competitor category is genuinely relevant to. Used to
 * cross-link competitor pages to the use cases where Menivor's differentiation
 * against that category is real (and the inverse: use case → competitors).
 */
const CATEGORY_THEMES: Readonly<Record<CompetitorCategory, readonly string[]>> =
  {
    clipper: ["screen-recording", "demos"],
    "avatar-generator": ["avatar", "faceless"],
    "caption-editor": ["captions", "scripting"],
    "faceless-generator": ["faceless", "ugc-ads"],
    "general-editor": ["screen-recording", "demos"],
    "managed-service": ["ugc-ads"],
    "text-to-video": ["faceless", "avatar"],
    "ugc-ad-generator": ["ugc-ads", "avatar"],
  };

// ---------------------------------------------------------------------------
// Edge queries (typed, deterministic, self-excluding).
// ---------------------------------------------------------------------------

/** ALTERNATIVE_TO / COMPARED_WITH: same-category competitors first, then rest. */
export function competitorAlternatives(
  slug: string,
  limit = 4,
): readonly Competitor[] {
  const current = getCompetitor(slug);
  const others = COMPETITORS.filter((c) => c.slug !== slug);
  if (!current) return others.slice(0, limit);
  const same = others.filter((c) => c.category === current.category);
  const rest = others.filter((c) => c.category !== current.category);
  return [...same, ...rest].slice(0, limit);
}

/** HAS_FEATURE (inverse): features a competitor truthfully has a peer of. */
export function featuresForCompetitor(slug: string): readonly Feature[] {
  return FEATURES.filter((f) => f.comparableCompetitors.includes(slug));
}

/** SOLVES (inverse): features that centrally solve a use case. */
export function featuresForUseCase(useCaseSlug: string): readonly Feature[] {
  return FEATURES.filter((f) => f.useCases.includes(useCaseSlug));
}

/** SOLVES: use cases a feature centrally solves. */
export function listUseCasesForFeature(featureSlug: string): readonly UseCase[] {
  const feature = getFeature(featureSlug);
  if (!feature) return [];
  return feature.useCases
    .map((s) => getUseCase(s))
    .filter((u): u is UseCase => Boolean(u));
}

/** HAS_FEATURE: competitors that truthfully offer a peer of this feature. */
export function competitorsForFeature(featureSlug: string): readonly Competitor[] {
  const feature = getFeature(featureSlug);
  if (!feature) return [];
  return feature.comparableCompetitors
    .map((s) => getCompetitor(s))
    .filter((c): c is Competitor => Boolean(c));
}

/** RELATED: use cases sharing a theme with the given one. */
export function relatedUseCasesByTheme(
  useCaseSlug: string,
  limit = 4,
): readonly UseCase[] {
  const theme = USE_CASE_THEME[useCaseSlug];
  if (!theme) return [];
  return USE_CASES.filter(
    (u) => u.slug !== useCaseSlug && USE_CASE_THEME[u.slug] === theme,
  ).slice(0, limit);
}

/** RELATED: features sharing a theme with the given one. */
export function relatedFeaturesByTheme(
  featureSlug: string,
  limit = 4,
): readonly Feature[] {
  const feature = getFeature(featureSlug);
  if (!feature) return [];
  return FEATURES.filter(
    (f) => f.slug !== featureSlug && f.theme === feature.theme,
  ).slice(0, limit);
}

/** Competitors whose category is genuinely relevant to a use case's theme. */
export function competitorsForUseCase(
  useCaseSlug: string,
  limit = 4,
): readonly Competitor[] {
  const theme = USE_CASE_THEME[useCaseSlug];
  if (!theme) return [];
  return COMPETITORS.filter((c) =>
    CATEGORY_THEMES[c.category].includes(theme),
  ).slice(0, limit);
}

/** Use cases where Menivor's differentiation against a competitor is real. */
export function listUseCasesForCompetitor(
  slug: string,
  limit = 4,
): readonly UseCase[] {
  const competitor = getCompetitor(slug);
  if (!competitor) return [];
  const themes = CATEGORY_THEMES[competitor.category];
  return USE_CASES.filter((u) =>
    themes.includes(USE_CASE_THEME[u.slug] ?? ""),
  ).slice(0, limit);
}

/** USES_PROVIDER: providers that power a feature. */
export function providersForFeature(featureSlug: string): readonly Provider[] {
  const feature = getFeature(featureSlug);
  if (!feature) return [];
  return feature.providers
    .map((s) => getProvider(s))
    .filter((p): p is Provider => Boolean(p));
}

/** Features a provider genuinely powers (provider ↔ feature). */
export function featuresForProvider(providerSlug: string): readonly Feature[] {
  const provider = getProvider(providerSlug);
  if (!provider) return [];
  return provider.relatedFeatures
    .map((s) => getFeature(s))
    .filter((f): f is Feature => Boolean(f));
}

/** RELATED: providers in the same marketplace category. */
export function relatedProvidersByCategory(
  providerSlug: string,
  limit = 4,
): readonly Provider[] {
  const provider = getProvider(providerSlug);
  if (!provider) return [];
  return PROVIDERS.filter(
    (p) => p.slug !== providerSlug && p.category === provider.category,
  ).slice(0, limit);
}

// ---------------------------------------------------------------------------
// Related-link builders (dead-link-guarded) consumed directly by the pages.
// ---------------------------------------------------------------------------

/** Related links for a `/features/{slug}` page: use cases + competitors + peers. */
export function relatedLinksForFeature(featureSlug: string): GraphLink[] {
  const useCaseLinks: GraphLink[] = listUseCasesForFeature(featureSlug).map((u) => ({
    href: `/tools/${u.slug}`,
    title: u.title,
    description: u.bestFor,
  }));
  const competitorLinks: GraphLink[] = competitorsForFeature(featureSlug).map(
    (c) => ({
      href: `/vs/${c.slug}`,
      title: `Menivor vs ${c.name}`,
      description: `How this compares against ${c.name}, ${c.categoryLabel}.`,
    }),
  );
  const featureLinks: GraphLink[] = relatedFeaturesByTheme(featureSlug).map(
    (f) => ({
      href: `/features/${f.slug}`,
      title: f.name,
      description: f.bestFor,
    }),
  );
  return guard([...useCaseLinks, ...featureLinks, ...competitorLinks]);
}

/** Provider links for a `/features/{slug}` page (kept separate for its own section). */
export function providerLinksForFeature(featureSlug: string): GraphLink[] {
  return guard(
    providersForFeature(featureSlug).map((p) => ({
      href: `/providers/${p.slug}`,
      title: p.name,
      description: p.whatItDoes,
    })),
  );
}

/** Related links for a `/providers/{slug}` page: features + peer providers. */
export function relatedLinksForProvider(providerSlug: string): GraphLink[] {
  const featureLinks: GraphLink[] = featuresForProvider(providerSlug).map(
    (f) => ({
      href: `/features/${f.slug}`,
      title: f.name,
      description: f.bestFor,
    }),
  );
  const providerLinks: GraphLink[] = relatedProvidersByCategory(
    providerSlug,
  ).map((p) => ({
    href: `/providers/${p.slug}`,
    title: p.name,
    description: p.whatItDoes,
  }));
  return guard([...featureLinks, ...providerLinks]);
}

/** Cross-entity links added to a `/vs/{slug}` and `/alternatives/{slug}` page. */
export function crossLinksForCompetitor(slug: string): {
  readonly features: GraphLink[];
  readonly useCases: GraphLink[];
} {
  const features = guard(
    featuresForCompetitor(slug).map((f) => ({
      href: `/features/${f.slug}`,
      title: f.name,
      description: f.bestFor,
    })),
  );
  const useCases = guard(
    listUseCasesForCompetitor(slug).map((u) => ({
      href: `/tools/${u.slug}`,
      title: u.title,
      description: u.bestFor,
    })),
  );
  return { features, useCases };
}

/** Cross-entity links added to a `/tools/{slug}` (use-case) page. */
export function crossLinksForUseCase(slug: string): {
  readonly features: GraphLink[];
  readonly competitors: GraphLink[];
} {
  const features = guard(
    featuresForUseCase(slug).map((f) => ({
      href: `/features/${f.slug}`,
      title: f.name,
      description: f.bestFor,
    })),
  );
  const competitors = guard(
    competitorsForUseCase(slug).map((c) => ({
      href: `/vs/${c.slug}`,
      title: `Menivor vs ${c.name}`,
      description: c.categoryLabel,
    })),
  );
  return { features, competitors };
}

// ---------------------------------------------------------------------------
// Cross-entity links for the template / platform / make surfaces. Each grouped
// set is guarded, so a related link can never point at a slug without a page.
// ---------------------------------------------------------------------------

/** Cross-entity links for a `/templates/{slug}` page. */
export function crossLinksForTemplate(slug: string): {
  readonly platforms: GraphLink[];
  readonly makeTypes: GraphLink[];
  readonly useCases: GraphLink[];
} {
  const template = getReelTemplate(slug);
  if (!template) return { platforms: [], makeTypes: [], useCases: [] };
  const platforms = guard(
    template.platforms
      .map((p) => getPlatform(p))
      .filter((p): p is NonNullable<typeof p> => Boolean(p))
      .map((p) => ({
        href: `/for/${p.slug}`,
        title: `AI video for ${p.name}`,
        description: p.bestFor,
      })),
  );
  const makeTypes = guard(
    template.makeTypes
      .map((m) => getMakeType(m))
      .filter((m): m is NonNullable<typeof m> => Boolean(m))
      .map((m) => ({
        href: `/make/${m.slug}`,
        title: m.title,
        description: m.bestFor,
      })),
  );
  const useCases = guard(
    template.useCases
      .map((u) => getUseCase(u))
      .filter((u): u is UseCase => Boolean(u))
      .map((u) => ({ href: `/tools/${u.slug}`, title: u.title, description: u.bestFor })),
  );
  return { platforms, makeTypes, useCases };
}

/** Cross-entity links for a `/for/{slug}` platform page. */
export function crossLinksForPlatform(slug: string): {
  readonly templates: GraphLink[];
  readonly makeTypes: GraphLink[];
  readonly useCases: GraphLink[];
} {
  const platform = getPlatform(slug);
  if (!platform) return { templates: [], makeTypes: [], useCases: [] };
  const templates = guard(
    platform.templates
      .map((t) => getReelTemplate(t))
      .filter((t): t is NonNullable<typeof t> => Boolean(t))
      .map((t) => ({
        href: `/templates/${t.slug}`,
        title: t.name,
        description: t.bestFor,
      })),
  );
  const makeTypes = guard(
    platform.makeTypes
      .map((m) => getMakeType(m))
      .filter((m): m is NonNullable<typeof m> => Boolean(m))
      .map((m) => ({
        href: `/make/${m.slug}`,
        title: m.title,
        description: m.bestFor,
      })),
  );
  const useCases = guard(
    platform.useCases
      .map((u) => getUseCase(u))
      .filter((u): u is UseCase => Boolean(u))
      .map((u) => ({ href: `/tools/${u.slug}`, title: u.title, description: u.bestFor })),
  );
  return { templates, makeTypes, useCases };
}

/** Cross-entity links for a `/make/{slug}` content-type page. */
export function crossLinksForMake(slug: string): {
  readonly templates: GraphLink[];
  readonly platforms: GraphLink[];
  readonly useCases: GraphLink[];
} {
  const makeType = getMakeType(slug);
  if (!makeType) return { templates: [], platforms: [], useCases: [] };
  const templates = guard(
    makeType.templates
      .map((t) => getReelTemplate(t))
      .filter((t): t is NonNullable<typeof t> => Boolean(t))
      .map((t) => ({
        href: `/templates/${t.slug}`,
        title: t.name,
        description: t.bestFor,
      })),
  );
  const platforms = guard(
    makeType.platforms
      .map((p) => getPlatform(p))
      .filter((p): p is NonNullable<typeof p> => Boolean(p))
      .map((p) => ({
        href: `/for/${p.slug}`,
        title: `AI video for ${p.name}`,
        description: p.bestFor,
      })),
  );
  const useCases = guard(
    makeType.useCases
      .map((u) => getUseCase(u))
      .filter((u): u is UseCase => Boolean(u))
      .map((u) => ({ href: `/tools/${u.slug}`, title: u.title, description: u.bestFor })),
  );
  return { templates, platforms, useCases };
}
