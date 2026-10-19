import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { Player } from "@/src/features/ott-player/Player";
import { getEmbed } from "@/src/features/ott-player/api";
import { ottEmbedLive } from "@/src/features/ott-player/flags";

export const metadata: Metadata = { robots: { index: false, follow: false } };

type Params = Promise<{ id: string }>;

/** The iframe player (oEmbed target): the player only, starting muted. */
export default async function EmbedPage({ params }: Readonly<{ params: Params }>) {
  if (!ottEmbedLive()) notFound();
  const { id } = await params;
  const title = await getEmbed(id, (await headers()).get("cf-ipcountry"));
  if (!title) notFound();
  return (
    <main className="bg-black p-0">
      {title.available_here ? <Player titleId={title.id} poster={title.artwork_url} autoPlay /> : (
        <p role="alert" className="p-4 text-white">This title is not available in your country.</p>
      )}
    </main>
  );
}
