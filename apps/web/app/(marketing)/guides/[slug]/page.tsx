import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { OFFER } from "@/lib/offer";
import {
  SITE_URL,
  compactSeoDescription,
  GUIDE_SLUGS,
  getGuide,
  relatedGuides,
  getUseCase,
  breadcrumbLd,
  faqPageLd,
  howToLd,
  articleLd,
  itemListLd,
  graphDocument,
} from "@/lib/seo";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { FaqSection } from "@/components/marketing/seo/FaqSection";
import {
  RelatedLinks,
  type RelatedLink,
} from "@/components/marketing/seo/RelatedLinks";
import { CtaBand } from "@/components/marketing/seo/CtaBand";
import { Badge } from "@/components/ui/badge";

interface PageProps {
  readonly params: Promise<{ slug: string }>;
}

export function generateStaticParams(): Array<{ slug: string }> {
  return GUIDE_SLUGS.map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const guide = getGuide(slug);
  if (!guide) return {};

  const canonical = `/guides/${guide.slug}`;
  const description = compactSeoDescription(guide.description);

  return {
    title: guide.title,
    description,
    keywords: [guide.keyword],
    alternates: { canonical },
    openGraph: {
      type: "article",
      url: `${SITE_URL}${canonical}`,
      siteName: "Menivor",
      title: `${guide.title} · Menivor`,
      description,
      publishedTime: guide.datePublished,
    },
    twitter: {
      card: "summary_large_image",
      title: `${guide.title} · Menivor`,
      description,
    },
  };
}

export default async function GuidePage({ params }: PageProps) {
  const { slug } = await params;
  const guide = getGuide(slug);
  if (!guide) notFound();

  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Guides", path: "/guides" },
    { name: guide.title, path: `/guides/${guide.slug}` },
  ];

  // Internal mesh: link to the tools this guide is about, and to peer guides.
  const toolLinks: RelatedLink[] = guide.relatedTools
    .map((toolSlug) => getUseCase(toolSlug))
    .filter((useCase): useCase is NonNullable<typeof useCase> =>
      Boolean(useCase),
    )
    .map((useCase) => ({
      href: `/tools/${useCase.slug}`,
      title: useCase.title,
      description: useCase.bestFor,
    }));

  const guideLinks: RelatedLink[] = relatedGuides(guide.slug).map((other) => ({
    href: `/guides/${other.slug}`,
    title: other.title,
    description: other.keyword,
  }));

  const jsonLd = graphDocument([
    articleLd({
      headline: guide.title,
      description: guide.description,
      path: `/guides/${guide.slug}`,
      datePublished: guide.datePublished,
    }),
    howToLd(
      guide.title,
      guide.description,
      guide.steps.map((step) => ({ name: step.name, text: step.text })),
    ),
    breadcrumbLd(crumbs),
    faqPageLd(guide.faqs),
    itemListLd(
      [...toolLinks, ...guideLinks].map((link) => ({
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

        <Badge variant="outline">Guide</Badge>
        <h1 className="mt-4 text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          {guide.title}
        </h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">
          {guide.lede}
        </p>

        <section className="mt-10 space-y-4 text-pretty leading-relaxed text-muted-foreground">
          {guide.intro.map((paragraph) => (
            <p key={paragraph.slice(0, 40)}>{paragraph}</p>
          ))}
        </section>

        <section className="mt-12">
          <h2 className="mb-4 text-2xl font-bold tracking-tight sm:text-3xl">
            Step by step
          </h2>
          <ol className="space-y-5">
            {guide.steps.map((step, index) => (
              <li key={step.name} className="flex items-start gap-3">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold text-primary">
                  {index + 1}
                </span>
                <span>
                  <span className="block font-semibold text-foreground">
                    {step.name}
                  </span>
                  <span className="mt-1 block text-pretty text-muted-foreground">
                    {step.text}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        </section>

        {guide.sections.map((section) => (
          <section key={section.heading} className="mt-12">
            <h2 className="mb-4 text-2xl font-bold tracking-tight sm:text-3xl">
              {section.heading}
            </h2>
            <div className="space-y-4 text-pretty leading-relaxed text-muted-foreground">
              {section.body.map((paragraph) => (
                <p key={paragraph.slice(0, 40)}>{paragraph}</p>
              ))}
            </div>
          </section>
        ))}

        <FaqSection faqs={guide.faqs} />

        {toolLinks.length > 0 ? (
          <RelatedLinks heading="Tools for this" links={toolLinks} />
        ) : null}

        <RelatedLinks heading="More guides" links={guideLinks} />

        <CtaBand
          heading="Put this guide into practice — make your first reel free"
          subheading={OFFER.signupSubheading}
        />
      </article>
    </div>
  );
}
