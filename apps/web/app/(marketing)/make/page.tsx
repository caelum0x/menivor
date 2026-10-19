import type { Metadata } from "next";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import {
  SITE_URL,
  MENIVOR_ONE_LINER,
  MAKE_TYPES,
  breadcrumbLd,
  softwareApplicationLd,
  itemListLd,
  graphDocument,
} from "@/lib/seo";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { CtaBand } from "@/components/marketing/seo/CtaBand";
import { OFFER } from "@/lib/offer";

const canonical = "/make";

export const metadata: Metadata = {
  title: "What to Make",
  description:
    "Make faceless videos, talking-head explainers, product demos, motivational quotes, and listicles with AI — each grounded in Menivor's screen-recording-to-reel pipeline.",
  alternates: { canonical },
  openGraph: {
    type: "website",
    url: `${SITE_URL}${canonical}`,
    siteName: "Menivor",
    title: "What to Make · Menivor",
    description:
      "Faceless videos, talking-head explainers, product demos, quote reels, and listicles — pick a content type and render it.",
  },
};

const crumbs = [
  { name: "Home", path: "/" },
  { name: "Make", path: "/make" },
];

export default function MakeIndexPage() {
  const jsonLd = graphDocument([
    softwareApplicationLd(MENIVOR_ONE_LINER),
    breadcrumbLd(crumbs),
    itemListLd(
      MAKE_TYPES.map((type) => ({
        name: type.title,
        path: `/make/${type.slug}`,
      })),
    ),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />

      <div className="mx-auto max-w-4xl">
        <Breadcrumbs crumbs={crumbs} />

        <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          What do you want to make?
        </h1>
        <p className="mt-4 max-w-2xl text-pretty text-lg text-muted-foreground">
          Start from the kind of video you need. Each guide explains the format
          and why Menivor fits it. Then paste a link and Menivor makes it for you.
        </p>

        <div className="mt-10 grid gap-3 sm:grid-cols-2">
          {MAKE_TYPES.map((type) => (
            <Link
              key={type.slug}
              href={`/make/${type.slug}`}
              className="group flex items-start justify-between gap-3 rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/40"
            >
              <span>
                <span className="block font-semibold text-foreground">
                  {type.title}
                </span>
                <span className="mt-0.5 block text-sm text-muted-foreground">
                  {type.lede}
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
