import type { Metadata } from "next";
import Link from "next/link";
import { OFFER } from "@/lib/offer";
import { notFound } from "next/navigation";
import {
  SITE_URL,
  compactSeoDescription,
  MENIVOR_ONE_LINER,
  PROVIDER_SLUGS,
  PROVIDER_CATEGORY_LABELS,
  getProvider,
  relatedLinksForProvider,
  breadcrumbLd,
  faqPageLd,
  itemListLd,
  softwareApplicationLd,
  graphDocument,
} from "@/lib/seo";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { FaqSection } from "@/components/marketing/seo/FaqSection";
import { RelatedLinks } from "@/components/marketing/seo/RelatedLinks";
import { CtaBand } from "@/components/marketing/seo/CtaBand";
import { Badge } from "@/components/ui/badge";

interface PageProps {
  readonly params: Promise<{ provider: string }>;
}

export function generateStaticParams(): Array<{ provider: string }> {
  return PROVIDER_SLUGS.map((provider) => ({ provider }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { provider: slug } = await params;
  const provider = getProvider(slug);
  if (!provider) return {};

  const description = compactSeoDescription(
    `${provider.whatItDoes} ${provider.howMenivorUses}`,
  );
  const canonical = `/providers/${provider.slug}`;

  return {
    title: `${provider.name} in Menivor`,
    description,
    keywords: [provider.keyword],
    alternates: { canonical },
    openGraph: {
      type: "website",
      url: `${SITE_URL}${canonical}`,
      siteName: "Menivor",
      title: `${provider.name} in Menivor`,
      description,
    },
    twitter: {
      card: "summary_large_image",
      title: `${provider.name} in Menivor`,
      description,
    },
  };
}

export default async function ProviderPage({ params }: PageProps) {
  const { provider: slug } = await params;
  const provider = getProvider(slug);
  if (!provider) notFound();

  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Providers", path: "/providers" },
    { name: provider.name, path: `/providers/${provider.slug}` },
  ];

  const related = relatedLinksForProvider(provider.slug);

  const jsonLd = graphDocument([
    softwareApplicationLd(MENIVOR_ONE_LINER),
    breadcrumbLd(crumbs),
    faqPageLd(provider.faqs),
    itemListLd(related.map((link) => ({ name: link.title, path: link.href }))),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />

      <article className="mx-auto max-w-3xl">
        <Breadcrumbs crumbs={crumbs} />

        <Badge variant="outline">
          {PROVIDER_CATEGORY_LABELS[provider.category]}
        </Badge>
        <h1 className="mt-4 text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          {provider.name} in Menivor
        </h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">
          {provider.whatItDoes}
        </p>
        <p className="mt-3 text-sm text-muted-foreground">
          Menivor is an independent product. Model and product names are
          trademarks of their owners, and naming one implies no affiliation or
          endorsement.
        </p>

        <section className="mt-10">
          <h2 className="mb-3 text-2xl font-bold tracking-tight sm:text-3xl">
            How it works in Menivor
          </h2>
          <p className="text-pretty leading-relaxed text-muted-foreground">
            {provider.howMenivorUses}
          </p>
        </section>

        <section className="mt-10 rounded-xl border border-border bg-card p-6">
          <h2 className="text-lg font-bold text-foreground">
            One account, one balance
          </h2>
          <p className="mt-2 text-pretty text-muted-foreground">
            You never manage a separate account or bill for any model Menivor
            uses. Standard reels spend reel credits; premium extras, when they
            are switched on, spend premium credits. A failed render never costs
            a credit.
          </p>
        </section>

        <FaqSection faqs={provider.faqs} />

        <RelatedLinks heading="Related in Menivor" links={related} />

        <CtaBand
          heading="Make a reel with Menivor"
          subheading={OFFER.signupSubheading}
        />

        <p className="mt-8 text-center text-sm text-muted-foreground">
          See the full list?{" "}
          <Link href="/providers" className="text-primary hover:underline">
            Browse every capability
          </Link>
          .
        </p>
      </article>
    </div>
  );
}
