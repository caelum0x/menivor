import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Check } from "lucide-react";
import {
  SITE_URL,
  VERTICAL_SLUGS,
  getVertical,
  isIndexableVertical,
  relatedVerticals,
  compactSeoDescription,
  breadcrumbLd,
  faqPageLd,
  howToLd,
  softwareApplicationLd,
  graphDocument,
} from "@/lib/seo";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { FaqSection } from "@/components/marketing/seo/FaqSection";
import { RelatedLinks } from "@/components/marketing/seo/RelatedLinks";
import { CtaBand } from "@/components/marketing/seo/CtaBand";
import { Badge } from "@/components/ui/badge";
import { PRICING_PLANS } from "@/components/marketing/plans";
import { VerticalStart } from "../_components/VerticalStart";
import { OFFER } from "@/lib/offer";

interface PageProps {
  readonly params: Promise<{ business: string }>;
}

export const dynamicParams = false;

export function generateStaticParams(): Array<{ business: string }> {
  return VERTICAL_SLUGS.map((business) => ({ business }));
}

function titleFor(plural: string): string {
  return `Video ads for ${plural}`;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { business } = await params;
  const vertical = getVertical(business);
  if (!vertical) return {};
  const canonical = `/video-ads/${vertical.slug}`;
  const title = titleFor(vertical.plural);
  const description = compactSeoDescription(
    `${vertical.lede} Paste your link, get three vertical reels with different opening hooks, a voiceover and captions.`,
  );
  return {
    title,
    description,
    keywords: [vertical.keyword],
    alternates: { canonical },
    robots: isIndexableVertical(vertical) ? undefined : { index: false, follow: true },
    openGraph: {
      type: "website",
      url: `${SITE_URL}${canonical}`,
      siteName: "Menivor",
      title: `${title} · Menivor`,
      description,
    },
    twitter: { card: "summary_large_image", title: `${title} · Menivor`, description },
  };
}

const STEPS = [
  { name: "Paste your link", text: "Your website, a product or listing page, an app store page or a social profile." },
  { name: "Sign up and start", text: OFFER.howStep },
  { name: "Pick your favorite", text: "Three 9:16 variants with different opening hooks. Edit the one you like, then download the MP4." },
] as const;

const OUTPUT = [
  "Three vertical reels (1080×1920 MP4), each opening with a different hook",
  "A script written from your page, voiced in English or Turkish",
  "A natural AI voiceover over your own footage",
  "Word-by-word captions burned in",
] as const;

export default async function VerticalPage({ params }: PageProps) {
  const { business } = await params;
  const vertical = getVertical(business);
  if (!vertical) notFound();

  const title = titleFor(vertical.plural);
  const path = `/video-ads/${vertical.slug}`;
  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Video ads", path: "/video-ads" },
    { name: title, path },
  ];
  const related = relatedVerticals(vertical.slug).map((other) => ({
    href: `/video-ads/${other.slug}`,
    title: titleFor(other.plural),
    description: other.lede,
  }));
  const [free, ...packs] = PRICING_PLANS;

  const jsonLd = graphDocument([
    softwareApplicationLd(vertical.lede),
    breadcrumbLd(crumbs),
    howToLd(`Make a video ad for your ${vertical.business}`, vertical.lede, STEPS.map((step) => ({ ...step }))),
    faqPageLd(vertical.faqs),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />
      <article className="mx-auto max-w-3xl">
        <Breadcrumbs crumbs={crumbs} />
        <Badge variant="outline">Video ads</Badge>
        <h1 className="mt-4 text-balance text-4xl font-bold tracking-tight sm:text-5xl">{title}</h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">{vertical.lede}</p>

        <div className="mt-8">
          <VerticalStart />
        </div>
        <p className="mt-3 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">What to paste:</span> {vertical.paste}{" "}
          <span className="whitespace-nowrap">For example: {vertical.exampleLink}</span>
        </p>

        <section className="mt-14">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">Three hooks for a {vertical.business}</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Examples we wrote to show the idea. Your reels get their own hooks, written from your page.
          </p>
          <ol className="mt-6 space-y-4">
            {vertical.hooks.map((hook, index) => (
              <li key={hook.line} className="glass rounded-xl p-5">
                <p className="text-xs font-semibold uppercase tracking-wide text-primary">Variant {index + 1}</p>
                <p className="mt-2 text-lg font-semibold text-foreground">&ldquo;{hook.line}&rdquo;</p>
                <p className="mt-1 text-sm text-muted-foreground">{hook.angle}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="mt-14 grid gap-8 md:grid-cols-2">
          <div>
            <h2 className="text-xl font-bold tracking-tight">What you get</h2>
            <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
              {OUTPUT.map((item) => (
                <li key={item} className="flex gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h2 className="text-xl font-bold tracking-tight">What the ad shows</h2>
            <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
              {vertical.show.map((item) => (
                <li key={item} className="flex gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="mt-14">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">Before you run it</h2>
          <ul className="mt-4 space-y-3 text-pretty leading-relaxed text-muted-foreground">
            {vertical.tips.map((tip) => (
              <li key={tip.slice(0, 40)}>{tip}</li>
            ))}
          </ul>
        </section>

        <section className="mt-14 rounded-xl border border-border bg-card p-6">
          <h2 className="text-2xl font-bold tracking-tight">Pricing</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {free ? `${free.description} ` : ""}One credit is one finished reel; a failed render gives the credit back,
            and credits never expire.
          </p>
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {packs.map((plan) => (
              <li key={plan.name} className="rounded-lg border border-border p-4">
                <p className="font-semibold text-foreground">{plan.name}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {plan.price} {plan.period}, {plan.credits} reels
                </p>
              </li>
            ))}
          </ul>
          <a href="/pricing" className="mt-4 inline-block text-sm font-medium text-primary underline underline-offset-4">
            Full pricing
          </a>
        </section>

        <FaqSection faqs={vertical.faqs} />

        <RelatedLinks heading="Video ads for other businesses" links={related} />

        <CtaBand
          heading={`Your ${vertical.business} ad, from one link`}
          subheading={OFFER.startSubheading}
        />
      </article>
    </div>
  );
}
