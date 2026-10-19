import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { OFFER } from "@/lib/offer";
import {
  SITE_URL,
  compactSeoDescription,
  MENIVOR_PIPELINE,
  FEATURE_SLUGS,
  getFeature,
  relatedLinksForFeature,
  providerLinksForFeature,
  breadcrumbLd,
  faqPageLd,
  itemListLd,
  softwareApplicationLd,
  graphDocument,
} from "@/lib/seo";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { FeatureList } from "@/components/marketing/seo/FeatureList";
import { FaqSection } from "@/components/marketing/seo/FaqSection";
import { RelatedLinks } from "@/components/marketing/seo/RelatedLinks";
import { CtaBand } from "@/components/marketing/seo/CtaBand";
import { Badge } from "@/components/ui/badge";

interface PageProps {
  readonly params: Promise<{ feature: string }>;
}

export function generateStaticParams(): Array<{ feature: string }> {
  return FEATURE_SLUGS.map((feature) => ({ feature }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { feature: slug } = await params;
  const feature = getFeature(slug);
  if (!feature) return {};

  const description = compactSeoDescription(
    `${feature.lede} ${feature.bestFor}`,
  );
  const canonical = `/features/${feature.slug}`;

  return {
    title: feature.name,
    description,
    keywords: [feature.keyword],
    alternates: { canonical },
    openGraph: {
      type: "website",
      url: `${SITE_URL}${canonical}`,
      siteName: "Menivor",
      title: `${feature.name} · Menivor`,
      description,
    },
    twitter: {
      card: "summary_large_image",
      title: `${feature.name} · Menivor`,
      description,
    },
  };
}

export default async function FeaturePage({ params }: PageProps) {
  const { feature: slug } = await params;
  const feature = getFeature(slug);
  if (!feature) notFound();

  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Features", path: "/features" },
    { name: feature.name, path: `/features/${feature.slug}` },
  ];

  const related = relatedLinksForFeature(feature.slug);
  const providerLinks = providerLinksForFeature(feature.slug);

  const jsonLd = graphDocument([
    softwareApplicationLd(`${feature.lede} ${MENIVOR_PIPELINE}`),
    breadcrumbLd(crumbs),
    faqPageLd(feature.faqs),
    itemListLd(
      [...related, ...providerLinks].map((link) => ({
        name: link.title,
        path: link.href,
      })),
    ),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />

      <article className="mx-auto max-w-3xl">
        <Breadcrumbs crumbs={crumbs} />

        <Badge variant="outline">Menivor feature</Badge>
        <h1 className="mt-4 text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          {feature.name}
        </h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">
          {feature.lede}
        </p>

        <section className="mt-10 space-y-4 text-pretty leading-relaxed text-muted-foreground">
          {feature.body.map((paragraph) => (
            <p key={paragraph.slice(0, 40)}>{paragraph}</p>
          ))}
        </section>

        <section className="mt-12 rounded-xl border border-border bg-card p-6">
          <h2 className="mb-4 text-2xl font-bold tracking-tight sm:text-3xl">
            What you get
          </h2>
          <FeatureList items={feature.highlights} />
          <p className="mt-5 text-sm text-muted-foreground">
            <span className="font-semibold text-foreground">Best for:</span>{" "}
            {feature.bestFor}
          </p>
        </section>

        {providerLinks.length > 0 ? (
          <RelatedLinks heading="Powered by" links={providerLinks} />
        ) : null}

        <FaqSection faqs={feature.faqs} />

        <RelatedLinks heading="Explore related" links={related} />

        <CtaBand
          heading="Make your first reel free"
          subheading={OFFER.signupSubheading}
        />
      </article>
    </div>
  );
}
