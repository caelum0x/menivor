import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight } from "lucide-react";
import { OFFER } from "@/lib/offer";
import {
  SITE_URL,
  compactSeoDescription,
  MENIVOR_PIPELINE,
  USE_CASE_SLUGS,
  getUseCase,
  relatedUseCases,
  crossLinksForUseCase,
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
  readonly params: Promise<{ usecase: string }>;
}

export function generateStaticParams(): Array<{ usecase: string }> {
  return USE_CASE_SLUGS.map((usecase) => ({ usecase }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { usecase: slug } = await params;
  const useCase = getUseCase(slug);
  if (!useCase) return {};

  const description = compactSeoDescription(
    `${useCase.lede} ${useCase.bestFor}`,
  );
  const canonical = `/tools/${useCase.slug}`;

  return {
    title: useCase.title,
    description,
    keywords: [useCase.keyword],
    alternates: { canonical },
    openGraph: {
      type: "website",
      url: `${SITE_URL}${canonical}`,
      siteName: "Menivor",
      title: `${useCase.title} · Menivor`,
      description,
    },
    twitter: {
      card: "summary_large_image",
      title: `${useCase.title} · Menivor`,
      description,
    },
  };
}

export default async function ToolPage({ params }: PageProps) {
  const { usecase: slug } = await params;
  const useCase = getUseCase(slug);
  if (!useCase) notFound();

  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Tools", path: "/tools" },
    { name: useCase.title, path: `/tools/${useCase.slug}` },
  ];

  const related = relatedUseCases(useCase.slug).map((other) => ({
    href: `/tools/${other.slug}`,
    title: other.title,
    description: other.keyword,
  }));

  // Cross-entity mesh: features that solve this job.
  const { features: featureLinks } = crossLinksForUseCase(useCase.slug);

  const jsonLd = graphDocument([
    softwareApplicationLd(`${useCase.lede} ${MENIVOR_PIPELINE}`),
    breadcrumbLd(crumbs),
    faqPageLd(useCase.faqs),
    itemListLd(
      [...related, ...featureLinks].map((link) => ({
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

        <Badge variant="outline">Menivor tool</Badge>
        <h1 className="mt-4 text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          {useCase.title}
        </h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">
          {useCase.lede}
        </p>

        {useCase.relatedTool ? (
          <Link
            href={useCase.relatedTool.href}
            className="mt-5 inline-flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-4 py-2 text-sm font-medium text-primary transition-colors hover:border-primary/60 hover:bg-primary/10"
          >
            {useCase.relatedTool.title}
            <ArrowUpRight className="size-4" />
          </Link>
        ) : null}

        <section className="mt-10 space-y-4 text-pretty leading-relaxed text-muted-foreground">
          {useCase.body.map((paragraph) => (
            <p key={paragraph.slice(0, 40)}>{paragraph}</p>
          ))}
        </section>

        <section className="mt-12 rounded-xl border border-border bg-card p-6">
          <h2 className="mb-4 text-2xl font-bold tracking-tight sm:text-3xl">
            What you get
          </h2>
          <FeatureList items={useCase.highlights} />
          <p className="mt-5 text-sm text-muted-foreground">
            <span className="font-semibold text-foreground">Best for:</span>{" "}
            {useCase.bestFor}
          </p>
        </section>

        <section className="mt-12">
          <h2 className="mb-4 text-2xl font-bold tracking-tight sm:text-3xl">
            How it works
          </h2>
          <ol className="space-y-3">
            {[
              "Paste a link, or upload a screen recording and write a short prompt.",
              "Menivor writes a hook-first script in English or Turkish and narrates it with a natural AI voice.",
              "Your footage or page recording fills the frame in the style you pick, and karaoke captions are burned in.",
              "Download your 1080×1920 reel and post it to TikTok, Reels and Shorts.",
            ].map((step, index) => (
              <li key={step} className="flex items-start gap-3">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold text-primary">
                  {index + 1}
                </span>
                <span className="text-pretty text-muted-foreground">
                  {step}
                </span>
              </li>
            ))}
          </ol>
        </section>

        <FaqSection faqs={useCase.faqs} />

        <RelatedLinks heading="More Menivor tools" links={related} />

        {featureLinks.length > 0 ? (
          <RelatedLinks
            heading="Features that power this"
            links={featureLinks}
          />
        ) : null}

        <CtaBand
          heading="Make your first reel free"
          subheading={OFFER.signupSubheading}
        />
      </article>
    </div>
  );
}
