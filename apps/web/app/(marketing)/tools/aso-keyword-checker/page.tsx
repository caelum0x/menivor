import type { Metadata } from "next";
import Link from "next/link";
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

const SLUG = "aso-keyword-checker";
const PATH = `/tools/${SLUG}`;
const TITLE = "Free ASO Keyword Checker: App Store Search Rank";
const DESCRIPTION =
  "Paste an App Store app link to check its rank in the top 50 results for generic terms derived from its own category and description, and see the competitors that show up most often. Free, no signup.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  keywords: ["aso keyword checker"],
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
    question: "Where do the search terms come from?",
    answer:
      "They are derived from the app's own App Store category and the words it repeats in its own description — not a paid keyword-research database. That keeps the check free and specific to the listing, though it will miss terms the listing itself never implies.",
  },
  {
    question: "How is rank checked?",
    answer:
      "Each term is run through Apple's public, keyless iTunes Search API, requesting the top 50 results for that term; the app's position in that list is its rank for the term. There is no official Apple popularity/difficulty score in this public API, so this tool reports rank and competitor overlap, not a 0-100 difficulty number.",
  },
  {
    question: "Does this work for Google Play?",
    answer:
      "No. Google Play has no public keyword-rank API, so this check only runs for App Store app links. Paste an App Store link (apps.apple.com) to use it.",
  },
  {
    question: "How are the top competitors chosen?",
    answer:
      "Across every term checked, the apps that appear in the top 50 results most often (other than the app being audited) are listed as the top competitors for that term set.",
  },
];

export default function AsoKeywordCheckerPage() {
  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Tools", path: "/tools" },
    { name: "ASO keyword checker", path: PATH },
  ];
  const jsonLd = graphDocument([breadcrumbLd(crumbs), faqPageLd(FAQS)]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />
      <article className="mx-auto max-w-3xl">
        <Breadcrumbs crumbs={crumbs} />
        <Badge variant="outline">Free tool: App growth</Badge>
        <h1 className="mt-4 text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          ASO keyword checker
        </h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">
          Paste an App Store app link. See its rank in the top 50 results for generic terms derived
          from its own category and description, via Apple&apos;s public Search API, plus the
          competitors that show up most often across those terms. No signup.
        </p>

        <AppAuditRunner variant="visibility-only" />

        <section className="mt-12 space-y-4 text-pretty leading-relaxed text-muted-foreground">
          <h2 className="text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            What this measures
          </h2>
          <p>
            This tool reads only public data: the listing itself (for its category and description)
            and Apple&apos;s public, keyless Search API (for rank among the top 50 results per term).
            Nothing here is scraped from an authenticated page, and nothing you paste is stored.
          </p>
          <p>
            Want the full packaging score — icon, screenshots, title, promo text and freshness — plus
            an exact rewrite suggestion for the same listing? Run the{" "}
            <Link href="/tools/app-store-audit" className="text-primary underline-offset-4 hover:underline">
              free App Store audit
            </Link>
            .
          </p>
        </section>

        <FaqSection faqs={FAQS} />

        <CtaBand
          heading="Turn this listing into a finished video, too"
          subheading={OFFER.signupSubheading}
        />
      </article>
    </div>
  );
}
