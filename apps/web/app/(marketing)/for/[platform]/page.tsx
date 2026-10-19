import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { OFFER } from "@/lib/offer";
import {
  SITE_URL,
  MENIVOR_PIPELINE,
  compactSeoDescription,
  PLATFORM_SLUGS,
  getPlatform,
  otherPlatforms,
  crossLinksForPlatform,
  breadcrumbLd,
  faqPageLd,
  articleLd,
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
  readonly params: Promise<{ platform: string }>;
}

export function generateStaticParams(): Array<{ platform: string }> {
  return PLATFORM_SLUGS.map((platform) => ({ platform }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { platform: slug } = await params;
  const platform = getPlatform(slug);
  if (!platform) return {};

  const canonical = `/for/${platform.slug}`;
  const description = compactSeoDescription(`${platform.lede} ${platform.bestFor}`);

  return {
    title: `AI Video for ${platform.name}`,
    description,
    keywords: [platform.keyword],
    alternates: { canonical },
    openGraph: {
      type: "article",
      url: `${SITE_URL}${canonical}`,
      siteName: "Menivor",
      title: `AI Video for ${platform.name} · Menivor`,
      description,
    },
    twitter: {
      card: "summary_large_image",
      title: `AI Video for ${platform.name} · Menivor`,
      description,
    },
  };
}

export default async function PlatformPage({ params }: PageProps) {
  const { platform: slug } = await params;
  const platform = getPlatform(slug);
  if (!platform) notFound();

  const canonical = `/for/${platform.slug}`;
  const crumbs = [
    { name: "Home", path: "/" },
    { name: "By platform", path: "/for" },
    { name: platform.name, path: canonical },
  ];

  const peers = otherPlatforms(platform.slug).map((other) => ({
    href: `/for/${other.slug}`,
    title: `AI video for ${other.name}`,
    description: other.bestFor,
  }));

  const { templates, makeTypes, useCases } = crossLinksForPlatform(
    platform.slug,
  );

  const jsonLd = graphDocument([
    softwareApplicationLd(`${platform.lede} ${MENIVOR_PIPELINE}`),
    articleLd({
      headline: `AI Video for ${platform.name}`,
      description: platform.lede,
      path: canonical,
      datePublished: "2026-09-23",
    }),
    breadcrumbLd(crumbs),
    faqPageLd(platform.faqs),
    itemListLd(
      [...templates, ...makeTypes, ...useCases, ...peers].map((link) => ({
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

        <Badge variant="outline">
          {platform.directPublish ? "Direct publish" : "Export & upload"}
        </Badge>
        <h1 className="mt-4 text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          AI video for {platform.name}
        </h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">
          {platform.lede}
        </p>

        <section className="mt-10 space-y-4 text-pretty leading-relaxed text-muted-foreground">
          {platform.body.map((paragraph) => (
            <p key={paragraph.slice(0, 40)}>{paragraph}</p>
          ))}
        </section>

        <section className="mt-12">
          <h2 className="mb-4 text-2xl font-bold tracking-tight sm:text-3xl">
            {platform.name} format specs
          </h2>
          <dl className="overflow-hidden rounded-md border border-border">
            {platform.specs.map((spec, index) => (
              <div
                key={spec.label}
                className={`grid grid-cols-[minmax(0,150px)_1fr] gap-4 p-4 ${
                  index % 2 === 1 ? "bg-secondary/30" : ""
                }`}
              >
                <dt className="font-medium text-muted-foreground">
                  {spec.label}
                </dt>
                <dd className="text-foreground">{spec.value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="mt-12 rounded-xl border border-border bg-card p-6">
          <h2 className="mb-4 text-2xl font-bold tracking-tight sm:text-3xl">
            What works on {platform.name}
          </h2>
          <FeatureList items={platform.highlights} />
          <p className="mt-5 text-sm text-muted-foreground">
            <span className="font-semibold text-foreground">Best for:</span>{" "}
            {platform.bestFor}
          </p>
        </section>

        <FaqSection faqs={platform.faqs} />

        {templates.length > 0 ? (
          <RelatedLinks
            heading={`Best templates for ${platform.name}`}
            links={templates}
          />
        ) : null}

        {makeTypes.length > 0 ? (
          <RelatedLinks heading="What to make" links={makeTypes} />
        ) : null}

        {useCases.length > 0 ? (
          <RelatedLinks heading="Use cases" links={useCases} />
        ) : null}

        <RelatedLinks heading="Other platforms" links={peers} />

        <CtaBand
          heading={`Make your first ${platform.name} reel free`}
          subheading={OFFER.signupSubheading}
        />
      </article>
    </div>
  );
}
