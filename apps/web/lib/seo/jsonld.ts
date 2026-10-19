/**
 * Structured-data (JSON-LD) builders shared by the programmatic pages. Kept as
 * plain object factories so pages stay declarative and the shapes are testable
 * without rendering. All URLs are absolute against SITE_URL.
 */

import { SITE_URL, MENIVOR_ONE_LINER } from "./site";
import { softwareApplicationEntity } from "./entity";

/** A single breadcrumb hop: a human label and an absolute-ish path. */
export interface Crumb {
  readonly name: string;
  readonly path: string;
}

/** A question/answer pair used for FAQPage structured data. */
export interface FaqEntry {
  readonly question: string;
  readonly answer: string;
}

/**
 * SoftwareApplication node describing Menivor, reused across pages. Offers come
 * from plan config through the entity module (MB1); no price is typed here.
 */
export function softwareApplicationLd(description: string = MENIVOR_ONE_LINER) {
  return softwareApplicationEntity(description);
}

/** BreadcrumbList node from an ordered list of crumbs. */
export function breadcrumbLd(crumbs: readonly Crumb[]) {
  return {
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((crumb, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: crumb.name,
      item: `${SITE_URL}${crumb.path}`,
    })),
  } as const;
}

/**
 * ItemList node for a set of related internal links (the graph mesh). Emitting
 * the related-links block as structured data gives AI answer engines an
 * explicit, ordered entity list to follow, on top of the visible links.
 */
export function itemListLd(items: readonly Crumb[]) {
  return {
    "@type": "ItemList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      url: `${SITE_URL}${item.path}`,
    })),
  } as const;
}

/** A single ordered step in a HowTo. */
export interface HowToStep {
  readonly name: string;
  readonly text: string;
}

/**
 * HowTo node for a step-by-step guide. Emitting HowTo alongside the visible
 * ordered list gives search and answer engines an explicit, structured recipe.
 */
export function howToLd(
  name: string,
  description: string,
  steps: readonly HowToStep[],
) {
  return {
    "@type": "HowTo",
    name,
    description,
    step: steps.map((step, index) => ({
      "@type": "HowToStep",
      position: index + 1,
      name: step.name,
      text: step.text,
    })),
  } as const;
}

/**
 * Article node for an editorial guide, attributed to the Menivor organization.
 * `path` is a site-relative path resolved against SITE_URL.
 */
export function articleLd(params: {
  readonly headline: string;
  readonly description: string;
  readonly path: string;
  readonly datePublished: string;
  readonly dateModified?: string;
}) {
  return {
    "@type": "Article",
    headline: params.headline,
    description: params.description,
    mainEntityOfPage: `${SITE_URL}${params.path}`,
    datePublished: params.datePublished,
    dateModified: params.dateModified ?? params.datePublished,
    author: { "@type": "Organization", name: "Menivor", url: SITE_URL },
    publisher: { "@type": "Organization", name: "Menivor", url: SITE_URL },
  } as const;
}

/** FAQPage node from question/answer pairs. */
export function faqPageLd(faqs: readonly FaqEntry[]) {
  return {
    "@type": "FAQPage",
    mainEntity: faqs.map((faq) => ({
      "@type": "Question",
      name: faq.question,
      acceptedAnswer: {
        "@type": "Answer",
        text: faq.answer,
      },
    })),
  } as const;
}

/** Wrap one or more nodes into a single @graph document ready to serialise. */
export function graphDocument(
  nodes: ReadonlyArray<Record<string, unknown>>,
): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@graph": nodes,
  };
}
