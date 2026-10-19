import type { Metadata } from "next";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import {
  SITE_URL,
  MENIVOR_ONE_LINER,
  PLATFORMS,
  breadcrumbLd,
  softwareApplicationLd,
  itemListLd,
  graphDocument,
} from "@/lib/seo";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { CtaBand } from "@/components/marketing/seo/CtaBand";
import { OFFER } from "@/lib/offer";

const canonical = "/for";

export const metadata: Metadata = {
  title: "AI Video by Platform",
  description:
    "AI video built for each platform — TikTok, Instagram Reels, YouTube Shorts, and LinkedIn. Native 9:16 export, hook-first scripts and karaoke captions, ready to download and post.",
  alternates: { canonical },
  openGraph: {
    type: "website",
    url: `${SITE_URL}${canonical}`,
    siteName: "Menivor",
    title: "AI Video by Platform · Menivor",
    description:
      "Native vertical video for TikTok, Instagram Reels, YouTube Shorts, and LinkedIn — sized, captioned, and ready to post.",
  },
};

const crumbs = [
  { name: "Home", path: "/" },
  { name: "By platform", path: "/for" },
];

export default function PlatformsIndexPage() {
  const jsonLd = graphDocument([
    softwareApplicationLd(MENIVOR_ONE_LINER),
    breadcrumbLd(crumbs),
    itemListLd(
      PLATFORMS.map((platform) => ({
        name: `AI video for ${platform.name}`,
        path: `/for/${platform.slug}`,
      })),
    ),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />

      <div className="mx-auto max-w-4xl">
        <Breadcrumbs crumbs={crumbs} />

        <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          AI video, built for your platform
        </h1>
        <p className="mt-4 max-w-2xl text-pretty text-lg text-muted-foreground">
          Same pipeline, tuned to each surface. Every reel exports native 9:16
          at 1080×1920 with karaoke captions — the difference is the formats,
          pacing, and specs that fit where you post.
        </p>

        <div className="mt-10 grid gap-3 sm:grid-cols-2">
          {PLATFORMS.map((platform) => (
            <Link
              key={platform.slug}
              href={`/for/${platform.slug}`}
              className="group flex items-start justify-between gap-3 rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/40"
            >
              <span>
                <span className="block font-semibold text-foreground">
                  AI video for {platform.name}
                </span>
                <span className="mt-0.5 block text-sm text-muted-foreground">
                  {platform.bestFor}
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
