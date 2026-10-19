import type { Metadata } from "next";
import Link from "next/link";
import { OFFER } from "@/lib/offer";
import {
  SITE_URL,
  MENIVOR_ONE_LINER,
  PROVIDERS,
  PROVIDER_CATEGORY_LABELS,
  breadcrumbLd,
  itemListLd,
  softwareApplicationLd,
  graphDocument,
  type Provider,
  type ProviderCategory,
} from "@/lib/seo";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { INDEPENDENT_PRODUCT_DISCLOSURE } from "@/components/marketing/LegalPage";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { CtaBand } from "@/components/marketing/seo/CtaBand";
import { ArrowUpRight } from "lucide-react";

const canonical = "/providers";

export const metadata: Metadata = {
  title: "What powers Menivor",
  description:
    "Explore the AI capabilities behind Menivor: voices, video, music, language models and model training, and which of them are available today.",
  alternates: { canonical },
  openGraph: {
    type: "website",
    url: `${SITE_URL}${canonical}`,
    siteName: "Menivor",
    title: "What powers Menivor",
    description:
      "The AI capabilities behind Menivor, grouped by what they do, and which are available today.",
  },
};

const crumbs = [
  { name: "Home", path: "/" },
  { name: "Providers", path: "/providers" },
];

/** Group providers by category, preserving first-seen category order. */
function groupByCategory(): ReadonlyArray<{
  readonly category: ProviderCategory;
  readonly providers: readonly Provider[];
}> {
  const order: ProviderCategory[] = [];
  const map = new Map<ProviderCategory, Provider[]>();
  for (const provider of PROVIDERS) {
    if (!map.has(provider.category)) {
      map.set(provider.category, []);
      order.push(provider.category);
    }
    map.get(provider.category)!.push(provider);
  }
  return order.map((category) => ({
    category,
    providers: map.get(category)!,
  }));
}

export default function ProvidersIndexPage() {
  const groups = groupByCategory();

  const jsonLd = graphDocument([
    softwareApplicationLd(MENIVOR_ONE_LINER),
    breadcrumbLd(crumbs),
    itemListLd(
      PROVIDERS.map((provider) => ({
        name: provider.name,
        path: `/providers/${provider.slug}`,
      })),
    ),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />

      <div className="mx-auto max-w-4xl">
        <Breadcrumbs crumbs={crumbs} />

        <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          What powers Menivor
        </h1>
        <p className="mt-4 max-w-2xl text-pretty text-lg text-muted-foreground">
          Every reel runs on Menivor&apos;s own pipeline: a written script, a
          natural AI voice, word captions and a style. Some extras use outside
          models; each page below says plainly whether it is available today and
          how it is paid for. You manage one balance, not a dozen accounts.
        </p>
        <p className="mt-3 max-w-2xl text-sm text-muted-foreground">
          {INDEPENDENT_PRODUCT_DISCLOSURE} Provider and model names are
          trademarks of their owners.
        </p>

        {groups.map((group) => (
          <section key={group.category} className="mt-12">
            <h2 className="mb-5 text-2xl font-bold tracking-tight sm:text-3xl">
              {PROVIDER_CATEGORY_LABELS[group.category]}
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {group.providers.map((provider) => (
                <Link
                  key={provider.slug}
                  href={`/providers/${provider.slug}`}
                  className="group flex items-start justify-between gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40"
                >
                  <span>
                    <span className="block font-semibold text-foreground">
                      {provider.name}
                    </span>
                    <span className="mt-0.5 block text-sm text-muted-foreground">
                      {provider.whatItDoes}
                    </span>
                  </span>
                  <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
                </Link>
              ))}
            </div>
          </section>
        ))}

        <CtaBand
          heading="Try Menivor"
          subheading={OFFER.signupSubheading}
        />
      </div>
    </div>
  );
}
