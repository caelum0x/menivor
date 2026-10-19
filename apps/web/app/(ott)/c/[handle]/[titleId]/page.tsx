import type { Metadata } from "next";
import Link from "next/link";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { Player } from "@/src/features/ott-player/Player";
import { getRelated, getTitlePage } from "@/src/features/ott-player/api";
import { ottStorefrontLive, ottSurfaceLive } from "@/src/features/ott-player/flags";
import { Offers } from "@/src/features/ott-checkout";
import { Chapters } from "@/src/features/ott-ai";
import { AskVideo } from "@/src/features/ott-discovery";
import { TitleActions } from "@/src/features/ott-auth";

type Params = Promise<{ handle: string; titleId: string }>;

export async function generateMetadata({ params }: Readonly<{ params: Params }>): Promise<Metadata> {
  if (!ottStorefrontLive()) return {};
  const { handle, titleId } = await params;
  const title = await getTitlePage(handle, titleId);
  return title ? { title: `${title.title} | ${title.channel.title}`, description: title.synopsis || title.title } : {};
}

export default async function TitleWatchPage({ params }: Readonly<{ params: Params }>) {
  if (!ottStorefrontLive()) notFound();
  const { handle, titleId } = await params;
  const country = (await headers()).get("cf-ipcountry");
  const title = await getTitlePage(handle, titleId, country);
  if (!title) notFound();
  // A related-titles failure never breaks the watch page.
  const related = ottSurfaceLive("discovery") ? await getRelated(title.id, country).catch(() => null) : null;
  return (
    <main className="mx-auto max-w-4xl px-4 py-6">
      <Link className="text-sm underline" href={`/c/${encodeURIComponent(handle)}`}>{title.channel.title}</Link>
      <h1 className="my-3 text-2xl font-semibold">{title.title}</h1>
      {title.available_here ? (
        <Player titleId={title.id} poster={title.artwork_url} handle={ottSurfaceLive("viewers") ? handle : undefined} />
      ) : (
        <p role="alert">This title is not available in your country.</p>
      )}
      {title.access_tier === "paid" && ottSurfaceLive("commerce") ? <Offers handle={handle} titleId={title.id} /> : null}
      {ottSurfaceLive("viewers") ? <TitleActions handle={handle} titleId={title.id} /> : null}
      {title.synopsis ? <p className="mt-4 text-sm text-muted-foreground">{title.synopsis}</p> : null}
      {title.credits && title.credits.length > 0 ? (
        <ul aria-label="Cast and crew" className="mt-3 space-y-1 text-sm">
          {title.credits.map((c) => <li key={`${c.name}-${c.role}`}>{c.name}, {c.role}</li>)}
        </ul>
      ) : null}
      {ottSurfaceLive("ai") ? <Chapters titleId={title.id} /> : null}
      {ottSurfaceLive("discovery") ? <AskVideo titleId={title.id} /> : null}
      {related && related.results.length > 0 ? (
        <section aria-label="More like this" className="mt-6">
          <h2 className="mb-2 text-sm font-semibold">More like this</h2>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {related.results.map((r) => (
              <li key={r.id}>
                <Link className="block text-sm underline" href={`/c/${encodeURIComponent(handle)}/${encodeURIComponent(r.id)}`}>{r.title}</Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </main>
  );
}
