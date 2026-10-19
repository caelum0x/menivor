import type { Metadata } from "next";
import Link from "next/link";
import {
  GALLERY_PATH,
  PRODUCTS,
  SITE_URL,
  jsonLdText,
  loadFeed,
  productLink,
  videoObject,
  type MegaphoneVideo,
} from "@/lib/seo/megaphone/feed";

// The feed changes every week without a redeploy, and this deploy has no
// persistent ISR cache, so the page renders per request (one small JSON fetch).
export const dynamic = "force-dynamic";

const PAGE_URL = `${SITE_URL}${GALLERY_PATH}`;

export const metadata: Metadata = {
  title: "Made with Menivor",
  description:
    "Real marketing reels we make every week for our own products with Menivor: page capture, script, free voice, captions and a dub, all from one link.",
  alternates: { canonical: GALLERY_PATH },
  openGraph: {
    title: "Made with Menivor",
    description: "Weekly product reels made end to end with Menivor.",
    url: PAGE_URL,
    type: "website",
  },
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

function VideoCard({ video }: Readonly<{ video: MegaphoneVideo }>) {
  const product = PRODUCTS[video.product];
  return (
    <article className="flex flex-col gap-3" id={video.id}>
      <video
        className="aspect-[9/16] w-full rounded-xl border border-white/[0.08] bg-black object-cover"
        src={video.videoUrl}
        poster={video.posterUrl}
        width={video.width}
        height={video.height}
        controls
        playsInline
        preload="none"
      />
      <div className="flex flex-col gap-1">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {product.name}
          {formatDate(video.uploadDate) ? ` · ${formatDate(video.uploadDate)}` : ""}
        </p>
        <h2 className="text-base font-semibold leading-snug">{video.title}</h2>
        <a className="text-sm underline underline-offset-4" href={productLink(video)} rel="noopener">
          Visit {product.name}
        </a>
        {video.dubs.map((dub) => (
          <a key={dub.language} className="text-sm text-muted-foreground underline underline-offset-4" href={dub.videoUrl}>
            Watch the {dub.language.toUpperCase()} dub
          </a>
        ))}
        {video.transcript ? (
          <details className="text-sm text-muted-foreground">
            <summary className="cursor-pointer">Transcript</summary>
            <p className="mt-2 leading-relaxed">{video.transcript}</p>
          </details>
        ) : null}
      </div>
    </article>
  );
}

/** `/made-with-menivor`: the weekly Megaphone reels for our own products. */
export default async function MadeWithMenivorPage() {
  const videos = await loadFeed();
  const structured = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "Made with Menivor",
    url: PAGE_URL,
    hasPart: videos.map((v) => videoObject(v, `${PAGE_URL}#${v.id}`)),
  };
  return (
    <div className="container py-12 lg:py-16">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdText(structured) }} />
      <div className="mb-10 max-w-2xl">
        <h1 className="mb-3 text-3xl font-bold tracking-tight">Made with Menivor</h1>
        <p className="text-muted-foreground">
          Every week we make the marketing reels for our own products with Menivor. Each one starts from a link: Menivor
          records the page, voices the script with a free voice, adds word by word captions and, for some, a dub into
          another language. No manual video editing.
        </p>
        <p className="mt-4">
          <Link className="underline underline-offset-4" href="/create">
            Make one from your link
          </Link>
        </p>
      </div>
      {videos.length ? (
        <div className="grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {videos.map((video) => (
            <VideoCard key={video.id} video={video} />
          ))}
        </div>
      ) : (
        <p className="text-muted-foreground">This week&apos;s reels are rendering. Check back soon.</p>
      )}
    </div>
  );
}
