import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { SITE_URL, VERTICALS, breadcrumbLd, itemListLd, graphDocument } from "@/lib/seo";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { VerticalStart } from "./_components/VerticalStart";

const DESCRIPTION =
  "Video ads for your kind of business: paste your website, listing or profile and get three vertical reels with different opening hooks, a voiceover and captions.";

export const metadata: Metadata = {
  title: "Video ads for your business",
  description: DESCRIPTION,
  alternates: { canonical: "/video-ads" },
  openGraph: { type: "website", url: `${SITE_URL}/video-ads`, siteName: "Menivor", title: "Video ads for your business · Menivor", description: DESCRIPTION },
};

export default function VideoAdsIndexPage() {
  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Video ads", path: "/video-ads" },
  ];
  const jsonLd = graphDocument([
    breadcrumbLd(crumbs),
    itemListLd(VERTICALS.map((vertical) => ({ name: `Video ads for ${vertical.plural}`, path: `/video-ads/${vertical.slug}` }))),
  ]);
  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />
      <div className="mx-auto max-w-3xl">
        <Breadcrumbs crumbs={crumbs} />
        <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-5xl">Video ads for your business</h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">{DESCRIPTION}</p>
        <div className="mt-8">
          <VerticalStart />
        </div>
      </div>
      <ul className="mx-auto mt-14 grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {VERTICALS.map((vertical) => (
          <li key={vertical.slug}>
            <Link
              href={`/video-ads/${vertical.slug}`}
              className="glass flex h-full items-center justify-between gap-3 rounded-xl p-4 text-sm font-medium text-foreground transition-colors hover:text-primary"
            >
              Video ads for {vertical.plural}
              <ArrowRight className="size-4 shrink-0" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
