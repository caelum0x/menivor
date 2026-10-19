import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import {
  SITE_URL,
  breadcrumbLd,
  faqPageLd,
  graphDocument,
  howToLd,
  itemListLd,
} from "@/lib/seo";
import { getFreeTool, type FreeTool } from "@/lib/seo/free-tools/catalog";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { FaqSection } from "@/components/marketing/seo/FaqSection";
import { RelatedLinks } from "@/components/marketing/seo/RelatedLinks";
import { CtaBand } from "@/components/marketing/seo/CtaBand";
import { Badge } from "@/components/ui/badge";
import { FreeToolWidget } from "./FreeToolWidget";
import { BitrateTable, PlatformSpecTable } from "./Calculators";

const DATE_PUBLISHED = "2026-10-08";

export function freeToolMetadata(slug: string): Metadata {
  const tool = getFreeTool(slug);
  if (!tool) return {};
  const canonical = `/tools/${tool.slug}`;
  return {
    title: tool.title,
    description: tool.description,
    keywords: [tool.keyword],
    alternates: { canonical },
    openGraph: {
      type: "website",
      url: `${SITE_URL}${canonical}`,
      siteName: "Menivor",
      title: `${tool.title} | Menivor`,
      description: tool.description,
    },
    twitter: {
      card: "summary_large_image",
      title: `${tool.title} | Menivor`,
      description: tool.description,
    },
  };
}

function webApplicationLd(tool: FreeTool) {
  return {
    "@type": "WebApplication",
    name: `${tool.shortName} by Menivor`,
    url: `${SITE_URL}/tools/${tool.slug}`,
    description: tool.description,
    applicationCategory: "MultimediaApplication",
    operatingSystem: "Any (runs in a web browser)",
    browserRequirements: "Requires JavaScript",
    isAccessibleForFree: true,
    datePublished: DATE_PUBLISHED,
    offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
    provider: { "@type": "Organization", name: "Menivor", url: SITE_URL },
  } as const;
}

function ExtraTable({ tool }: { readonly tool: FreeTool }) {
  if (tool.widget === "aspect") return <PlatformSpecTable />;
  if (tool.widget === "bitrate") return <BitrateTable />;
  return null;
}

export function FreeToolPage({ slug }: { readonly slug: string }) {
  const tool = getFreeTool(slug);
  if (!tool) notFound();

  const path = `/tools/${tool.slug}`;
  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Tools", path: "/tools" },
    { name: tool.shortName, path },
  ];
  const related = tool.related
    .map((other) => getFreeTool(other))
    .filter((other): other is FreeTool => Boolean(other))
    .map((other) => ({ href: `/tools/${other.slug}`, title: other.shortName, description: other.lede.split(". ")[0] }));

  const jsonLd = graphDocument([
    webApplicationLd(tool),
    breadcrumbLd(crumbs),
    faqPageLd(tool.faqs),
    howToLd(
      `How to use the ${tool.shortName.toLowerCase()}`,
      tool.lede,
      tool.steps.map((step, index) => ({ name: `Step ${index + 1}`, text: step })),
    ),
    itemListLd([...related, ...tool.links].map((link) => ({ name: link.title, path: link.href }))),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />
      <article className="mx-auto max-w-3xl">
        <Breadcrumbs crumbs={crumbs} />
        <Badge variant="outline">Free tool: {tool.category}</Badge>
        <h1 className="mt-4 text-balance text-4xl font-bold tracking-tight sm:text-5xl">{tool.h1}</h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">{tool.lede}</p>
        <p className="mt-3 flex items-start gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <span>{tool.privacy} No signup needed.</span>
        </p>

        <FreeToolWidget widget={tool.widget} />

        <section className="mt-12">
          <h2 className="mb-4 text-2xl font-bold tracking-tight sm:text-3xl">How to use it</h2>
          <ol className="space-y-3">
            {tool.steps.map((step, index) => (
              <li key={step} className="flex items-start gap-3">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold text-primary">{index + 1}</span>
                <span className="text-pretty text-muted-foreground">{step}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className="mt-12 space-y-4 text-pretty leading-relaxed text-muted-foreground">
          <h2 className="text-2xl font-bold tracking-tight text-foreground sm:text-3xl">About this {tool.shortName.toLowerCase()}</h2>
          {tool.body.map((paragraph) => (
            <p key={paragraph.slice(0, 48)}>{paragraph}</p>
          ))}
        </section>

        <ExtraTable tool={tool} />

        <FaqSection faqs={tool.faqs} />

        <RelatedLinks heading="More free tools" links={related} />
        <RelatedLinks heading="Guides and video makers" links={tool.links} />

        <p className="mt-8 text-sm text-muted-foreground">
          See all <Link href="/tools" className="text-primary underline-offset-4 hover:underline">free video tools</Link>.
        </p>

        <CtaBand
          heading="Skip the busywork: get finished videos"
          subheading="Paste a link or type a topic. Menivor writes the hook and script, records the voiceover, adds footage and word-by-word captions, and renders ready-to-post vertical videos in 1080 x 1920."
        />
      </article>
    </div>
  );
}
