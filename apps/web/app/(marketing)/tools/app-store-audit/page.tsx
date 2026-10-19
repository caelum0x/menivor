import type { Metadata } from "next";
import { OFFER } from "@/lib/offer";
import {
  SITE_URL,
  breadcrumbLd,
  faqPageLd,
  graphDocument,
  type FaqEntry,
} from "@/lib/seo";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { FaqSection } from "@/components/marketing/seo/FaqSection";
import { CtaBand } from "@/components/marketing/seo/CtaBand";
import { Badge } from "@/components/ui/badge";
import { AppAuditRunner } from "@/components/marketing/app-audit/AppAuditRunner";

const SLUG = "app-store-audit";
const PATH = `/tools/${SLUG}`;
const TITLE = "Free App Store Audit: Score Your Listing's Packaging";
const DESCRIPTION =
  "Paste an App Store or Google Play app link for a free packaging score (icon, screenshots, title, promo text, freshness), a search-visibility check, and an exact rewrite suggestion. No signup.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  keywords: ["app store audit", "app store screenshot checker"],
  alternates: { canonical: PATH },
  openGraph: {
    type: "website",
    url: `${SITE_URL}${PATH}`,
    siteName: "Menivor",
    title: `${TITLE} | Menivor`,
    description: DESCRIPTION,
  },
  twitter: {
    card: "summary_large_image",
    title: `${TITLE} | Menivor`,
    description: DESCRIPTION,
  },
};

const FAQS: readonly FaqEntry[] = [
  {
    question: "What does the free App Store audit check?",
    answer:
      "Five packaging checks from the App Store packaging rules (icon readability, first-3-screenshot story, title/subtitle outcome, promo text benefit, freshness), a search-visibility check against 8-10 generic terms via Apple's public Search API, and an exact promo-text and subtitle rewrite built only from your own listing's facts.",
  },
  {
    question: "Is this a real score or a guess?",
    answer:
      "It is a mix. Rating, price, screenshot count, description length and update date are read directly from the public listing. Icon readability and whether the screenshots tell a story are pixel/text heuristics, labelled \"heuristic\" on the page, not a human design review — a person should still look at the icon and screenshots themselves.",
  },
  {
    question: "Does this work for Google Play apps?",
    answer:
      "The packaging score runs for both App Store and Google Play listings. Search-term rank and competitor overlap only run for App Store listings, because Google Play has no public keyword-rank API.",
  },
  {
    question: "Do you store the link or the listing I paste?",
    answer:
      "No account and no sign-in are needed to run the audit. The listing is read live from Apple's or Google's public pages each time (search results are cached for one day to avoid hammering the public API).",
  },
  {
    question: "Where do the rewrite suggestions come from?",
    answer:
      "An AI pass over your listing's own title, category and description text, routed through Menivor's Relay LLM gateway — it is told never to invent features, prices or numbers that are not already in your listing. If the AI writer is unavailable, a plain template built from the same facts is used instead and labelled accordingly.",
  },
];

interface PageProps {
  readonly searchParams?: Promise<{ url?: string }>;
}

export default async function AppStoreAuditPage({ searchParams }: PageProps) {
  // "Connect your store" (Settings -> Integrations) links a connected app
  // straight here with ?url=<store link> so a creator never has to copy/paste
  // their own listing's URL by hand.
  const initialUrl = (await searchParams)?.url ?? "";
  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Tools", path: "/tools" },
    { name: "App Store audit", path: PATH },
  ];
  const jsonLd = graphDocument([breadcrumbLd(crumbs), faqPageLd(FAQS)]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />
      <article className="mx-auto max-w-3xl">
        <Breadcrumbs crumbs={crumbs} />
        <Badge variant="outline">Free tool: App growth</Badge>
        <h1 className="mt-4 text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          Free App Store audit
        </h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">
          Paste an App Store or Google Play app link. Get a packaging score against the five-point
          checklist (icon, screenshots, title, promo text, freshness), a search-visibility check
          for App Store listings, and an exact rewrite suggestion for the promo text and subtitle —
          built only from your own listing&apos;s facts. No signup.
        </p>

        <AppAuditRunner initialUrl={initialUrl} />

        <section className="mt-12 space-y-4 text-pretty leading-relaxed text-muted-foreground">
          <h2 className="text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            What this checks, and what is a heuristic
          </h2>
          <p>
            Rating, rating count, price, screenshot count, description length, category and last-update
            date come straight from Apple&apos;s public iTunes Lookup API or the public Google Play
            listing page — the same data Apple and Google already show shoppers.
          </p>
          <p>
            Icon readability at a 60×60pt thumbnail and whether the first three screenshots read as a
            story are judgment calls a human makes well and an algorithm does not: those two checks are
            marked as heuristics on the page, built from pixel contrast and screenshot count, not a
            design review.
          </p>
          <p>
            Search visibility checks the app&apos;s position in the top 50 App Store results for 8-10
            generic terms derived from its category and description, using Apple&apos;s public, keyless
            Search API, and lists the competitors that show up most often across those terms. This part
            only runs for App Store listings: Google Play has no equivalent public rank API.
          </p>
        </section>

        <FaqSection faqs={FAQS} />

        <CtaBand
          heading="See the fixes as a finished video, too"
          subheading={OFFER.signupSubheading}
        />
      </article>
    </div>
  );
}
