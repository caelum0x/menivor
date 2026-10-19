import type { Metadata } from "next";
import Link from "next/link";
import { GalleryFeed, PublishPicker, RecreatePanel } from "@/src/features/gallery";

export const metadata: Metadata = {
  title: "Gallery",
  description: "Reels people chose to share. Recreate any of them with your own topic or link.",
  alternates: { canonical: "/gallery" },
};

type GallerySearchParams = {
  recreate?: string | string[];
  publish?: string | string[];
  image?: string | string[];
};

function first(value: string | string[] | undefined): string {
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

/** `/gallery` (MH3): the opt-in feed; `?recreate=<id>` opens Recreate, `?publish=1` lets you show a reel. */
export default async function GalleryPage({
  searchParams,
}: Readonly<{ searchParams: Promise<GallerySearchParams> }>) {
  const query = await searchParams;
  const recreate = first(query.recreate).slice(0, 32);
  const publish = first(query.publish) === "1";
  return (
    <div className="container py-12 lg:py-16">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Gallery</h1>
          <p className="text-muted-foreground">Reels people chose to share. Recreate any of them with your own topic.</p>
        </div>
        {!publish && !recreate ? (
          <Link className="text-sm underline underline-offset-4" href="/gallery?publish=1">Show one of your reels</Link>
        ) : null}
      </div>
      {recreate ? (
        <RecreatePanel itemId={recreate} imageKey={first(query.image).slice(0, 512)} />
      ) : publish ? (
        <PublishPicker />
      ) : (
        <GalleryFeed />
      )}
    </div>
  );
}
