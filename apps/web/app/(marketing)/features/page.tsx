import type { Metadata } from "next";
import Link from "next/link";
import {
  SITE_URL,
  MENIVOR_ONE_LINER,
  FEATURES,
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

const canonical = "/features";

export const metadata: Metadata = {
  title: "Menivor Features",
  description:
    "What Menivor does, one feature per page: hook-first scripts from a link or a topic, AI voiceover, word-by-word captions and ready-to-post vertical reels.",
  alternates: { canonical },
  openGraph: {
    type: "website",
    url: `${SITE_URL}${canonical}`,
    siteName: "Menivor",
    title: "Menivor Features · reels from a link, a topic or your own video",
    description:
      "The capabilities behind Menivor's reels: hook-first scripts, AI voiceover, word-by-word captions and 9:16 export, explained one feature at a time.",
  },
};

const crumbs = [
  { name: "Home", path: "/" },
  { name: "Features", path: "/features" },
];

export default function FeaturesIndexPage() {
  const jsonLd = graphDocument([
    softwareApplicationLd(MENIVOR_ONE_LINER),
    breadcrumbLd(crumbs),
    itemListLd(
      FEATURES.map((feature) => ({
        name: feature.name,
        path: `/features/${feature.slug}`,
      })),
    ),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />

      <div className="mx-auto max-w-4xl">
        <Breadcrumbs crumbs={crumbs} />

        <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          Menivor features
        </h1>
        <p className="mt-4 max-w-2xl text-pretty text-lg text-muted-foreground">
          Menivor turns a link, a topic or your own footage into ready-to-post
          vertical reels. Here is each capability behind that pipeline,
          explained on its own page.
        </p>

        <section className="mt-10 space-y-4 text-muted-foreground">
          <h2 className="text-2xl font-semibold text-foreground">
            One render connects the full production chain
          </h2>
          <p>
            Paste a link, type a topic or upload a screen recording. Menivor
            turns that into hook-first scripts, generates the voice track, and
            uses the word timing of that audio to drive the word-by-word
            captions. Each run renders vertical reels with different opening
            hooks and exports them as 1080 by 1920 MP4 files. Already have a
            video? Menivor can add the captions to it using its own audio.
          </p>
          <p>
            The same pipeline supports English and Turkish from the script
            through the rendered captions. You can reuse a successful layout as
            a template, check the finished reel, then download it and post it
            to TikTok, Instagram Reels or YouTube Shorts. Open a feature below
            for its inputs, output, and place in the render process.
          </p>
          <p>
            Prepare a clean source recording at the highest resolution available
            and keep important controls away from the edges of the frame. Review
            names and technical terms in the generated script before rendering.
            After export, check caption timing, the safe zones and the opening
            hook on a phone. Save the approved layout as a template when you need
            a consistent series.
          </p>
        </section>

        <div className="mt-10 grid gap-3 sm:grid-cols-2">
          {FEATURES.map((feature) => (
            <Link
              key={feature.slug}
              href={`/features/${feature.slug}`}
              className="group flex items-start justify-between gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40"
            >
              <span>
                <span className="block font-semibold text-foreground">
                  {feature.name}
                </span>
                <span className="mt-0.5 block text-sm text-muted-foreground">
                  {feature.bestFor}
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
