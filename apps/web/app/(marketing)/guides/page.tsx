import type { Metadata } from "next";
import Link from "next/link";
import {
  SITE_URL,
  MENIVOR_ONE_LINER,
  GUIDES,
  breadcrumbLd,
  itemListLd,
  softwareApplicationLd,
  graphDocument,
} from "@/lib/seo";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { CtaBand } from "@/components/marketing/seo/CtaBand";
import { ArrowUpRight } from "lucide-react";
import { OFFER } from "@/lib/offer";

const canonical = "/guides";

export const metadata: Metadata = {
  title: "AI Video Guides",
  description:
    "How-to guides for AI video: faceless channels, video ads, TikTok hooks, karaoke captions, and turning screen recordings into reels.",
  alternates: { canonical },
  openGraph: {
    type: "website",
    url: `${SITE_URL}${canonical}`,
    siteName: "Menivor",
    title: "AI Video Guides · Menivor",
    description:
      "Practical, honest how-to guides for making AI video that actually performs — from faceless channels to UGC ad testing.",
  },
};

const crumbs = [
  { name: "Home", path: "/" },
  { name: "Guides", path: "/guides" },
];

export default function GuidesIndexPage() {
  const jsonLd = graphDocument([
    softwareApplicationLd(MENIVOR_ONE_LINER),
    breadcrumbLd(crumbs),
    itemListLd(
      GUIDES.map((guide) => ({
        name: guide.title,
        path: `/guides/${guide.slug}`,
      })),
    ),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />

      <div className="mx-auto max-w-4xl">
        <Breadcrumbs crumbs={crumbs} />

        <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          AI video guides
        </h1>
        <p className="mt-4 max-w-2xl text-pretty text-lg text-muted-foreground">
          Practical, honest how-to guides for making short-form video that
          performs — faceless channels, video ads, hooks, captions, and
          turning screen recordings into finished reels.
        </p>

        <div className="mt-10 grid gap-3 sm:grid-cols-2">
          {GUIDES.map((guide) => (
            <Link
              key={guide.slug}
              href={`/guides/${guide.slug}`}
              className="group flex items-start justify-between gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40"
            >
              <span>
                <span className="block font-semibold text-foreground">
                  {guide.title}
                </span>
                <span className="mt-0.5 block text-sm text-muted-foreground">
                  {guide.lede}
                </span>
              </span>
              <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
            </Link>
          ))}
        </div>

        <CtaBand
          heading="Make your first reel free"
          subheading={OFFER.signupSubheading}
        />
      </div>
    </div>
  );
}
