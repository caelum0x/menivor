import type { Metadata } from "next";
import Link from "next/link";
import {
  SITE_URL,
  MENIVOR_ONE_LINER,
  USE_CASES,
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
import {
  FREE_TOOLS,
  FREE_TOOL_CATEGORIES,
} from "@/lib/seo/free-tools/catalog";

const canonical = "/tools";

export const metadata: Metadata = {
  title: "Free Video Tools: Hooks, Scripts, Subtitles and More",
  description:
    "Free tools for short-form video: TikTok hook and script generator, subtitle generator, SRT to VTT, voiceover, hashtags, titles and video calculators.",
  alternates: { canonical },
  openGraph: {
    type: "website",
    url: `${SITE_URL}${canonical}`,
    siteName: "Menivor",
    title: "Free Video Tools | Menivor",
    description:
      "Free, working tools for TikTok, Reels and Shorts creators, plus Menivor's tools for turning a link or a topic into finished videos.",
  },
};

const crumbs = [
  { name: "Home", path: "/" },
  { name: "Tools", path: "/tools" },
];

export default function ToolsIndexPage() {
  const jsonLd = graphDocument([
    softwareApplicationLd(MENIVOR_ONE_LINER),
    breadcrumbLd(crumbs),
    itemListLd(FREE_TOOLS.map((tool) => ({ name: tool.shortName, path: `/tools/${tool.slug}` }))),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />

      <div className="mx-auto max-w-4xl">
        <Breadcrumbs crumbs={crumbs} />

        <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          Free video tools
        </h1>
        <p className="mt-4 max-w-2xl text-pretty text-lg text-muted-foreground">
          Working tools for short-form video, free and without signup: write
          hooks and scripts, generate subtitles, convert caption files, make a
          voiceover and do the video math. Then, when you want finished
          videos, Menivor makes them from a link or a topic.
        </p>

        <section id="free-tools" className="mt-10 space-y-8">
          {FREE_TOOL_CATEGORIES.map((category) => (
            <div key={category}>
              <h2 className="mb-3 text-xl font-semibold tracking-tight">{category}</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {FREE_TOOLS.filter((tool) => tool.category === category).map((tool) => (
                  <Link
                    key={tool.slug}
                    href={`/tools/${tool.slug}`}
                    className="group flex items-start justify-between gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40"
                  >
                    <span>
                      <span className="block font-semibold text-foreground">{tool.shortName}</span>
                      <span className="mt-0.5 block text-sm text-muted-foreground">{tool.lede.split(". ")[0]}</span>
                    </span>
                    <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </section>

        <h2 className="mt-14 text-2xl font-bold tracking-tight sm:text-3xl">
          Menivor video makers
        </h2>
        <p className="mt-3 max-w-2xl text-pretty text-muted-foreground">
          One pipeline, many jobs. Menivor turns a link, a topic or a screen
          recording into a ready-to-post reel with a voiceover and karaoke
          captions.
        </p>

        <div className="mt-6 grid gap-3 sm:grid-cols-2">
          {USE_CASES.map((useCase) => (
            <Link
              key={useCase.slug}
              href={`/tools/${useCase.slug}`}
              className="group flex items-start justify-between gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40"
            >
              <span>
                <span className="block font-semibold text-foreground">
                  {useCase.title}
                </span>
                <span className="mt-0.5 block text-sm text-muted-foreground">
                  {useCase.bestFor}
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
