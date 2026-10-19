import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { OFFER } from "@/lib/offer";
import {
  SITE_URL,
  MENIVOR_PIPELINE,
  compactSeoDescription,
  MAKE_TYPE_SLUGS,
  getMakeType,
  otherMakeTypes,
  crossLinksForMake,
  breadcrumbLd,
  faqPageLd,
  howToLd,
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
  readonly params: Promise<{ type: string }>;
}

export function generateStaticParams(): Array<{ type: string }> {
  return MAKE_TYPE_SLUGS.map((type) => ({ type }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { type: slug } = await params;
  const makeType = getMakeType(slug);
  if (!makeType) return {};

  const canonical = `/make/${makeType.slug}`;
  const description = compactSeoDescription(`${makeType.lede} ${makeType.bestFor}`);

  return {
    title: makeType.title,
    description,
    keywords: [makeType.keyword],
    alternates: { canonical },
    openGraph: {
      type: "website",
      url: `${SITE_URL}${canonical}`,
      siteName: "Menivor",
      title: `${makeType.title} · Menivor`,
      description,
    },
    twitter: {
      card: "summary_large_image",
      title: `${makeType.title} · Menivor`,
      description,
    },
  };
}

export default async function MakePage({ params }: PageProps) {
  const { type: slug } = await params;
  const makeType = getMakeType(slug);
  if (!makeType) notFound();

  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Make", path: "/make" },
    { name: makeType.title, path: `/make/${makeType.slug}` },
  ];

  const peers = otherMakeTypes(makeType.slug).map((other) => ({
    href: `/make/${other.slug}`,
    title: other.title,
    description: other.bestFor,
  }));

  const { templates, platforms, useCases } = crossLinksForMake(makeType.slug);

  const jsonLd = graphDocument([
    softwareApplicationLd(`${makeType.lede} ${MENIVOR_PIPELINE}`),
    breadcrumbLd(crumbs),
    howToLd(
      makeType.title,
      makeType.lede,
      makeType.steps.map((step) => ({ name: step.name, text: step.text })),
    ),
    faqPageLd(makeType.faqs),
    itemListLd(
      [...templates, ...platforms, ...useCases, ...peers].map((link) => ({
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

        <Badge variant="outline">Make</Badge>
        <h1 className="mt-4 text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          {makeType.title}
        </h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">
          {makeType.lede}
        </p>

        <section className="mt-10 space-y-4 text-pretty leading-relaxed text-muted-foreground">
          {makeType.body.map((paragraph) => (
            <p key={paragraph.slice(0, 40)}>{paragraph}</p>
          ))}
        </section>

        <section className="mt-12 rounded-xl border border-border bg-card p-6">
          <h2 className="mb-4 text-2xl font-bold tracking-tight sm:text-3xl">
            What you get
          </h2>
          <FeatureList items={makeType.highlights} />
          <p className="mt-5 text-sm text-muted-foreground">
            <span className="font-semibold text-foreground">Best for:</span>{" "}
            {makeType.bestFor}
          </p>
        </section>

        <section className="mt-12">
          <h2 className="mb-4 text-2xl font-bold tracking-tight sm:text-3xl">
            How Menivor makes it
          </h2>
          <ol className="space-y-3">
            {makeType.steps.map((step, index) => (
              <li key={step.name} className="flex items-start gap-3">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold text-primary">
                  {index + 1}
                </span>
                <span>
                  <span className="block font-semibold text-foreground">
                    {step.name}
                  </span>
                  <span className="mt-0.5 block text-pretty text-muted-foreground">
                    {step.text}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        </section>

        <FaqSection faqs={makeType.faqs} />

        {templates.length > 0 ? (
          <RelatedLinks heading="Templates that make this" links={templates} />
        ) : null}

        {platforms.length > 0 ? (
          <RelatedLinks heading="Best platforms for it" links={platforms} />
        ) : null}

        {useCases.length > 0 ? (
          <RelatedLinks heading="Use cases" links={useCases} />
        ) : null}

        <RelatedLinks heading="Other things to make" links={peers} />

        <CtaBand
          heading="Make your first reel free"
          subheading={OFFER.signupSubheading}
        />
      </article>
    </div>
  );
}
