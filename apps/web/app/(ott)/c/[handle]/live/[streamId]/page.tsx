import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { LiveChat, LivePlayer } from "@/src/features/ott-live-chat";
import { ottStorefrontLive, ottSurfaceLive } from "@/src/features/ott-player/flags";

type Params = Promise<{ handle: string; streamId: string }>;

export const metadata: Metadata = { title: "Live", robots: { index: false } };

/** `/c/[handle]/live/[streamId]` (MV10, MV11): the live player and, when on, the chat. */
export default async function LivePage({ params }: Readonly<{ params: Params }>) {
  if (!ottStorefrontLive() || !ottSurfaceLive("live")) notFound();
  const { handle, streamId } = await params;
  return (
    <main className="mx-auto grid max-w-6xl gap-4 px-4 py-6 lg:grid-cols-[2fr_1fr]">
      <div>
        <Link className="text-sm underline" href={`/c/${encodeURIComponent(handle)}`}>Back to the channel</Link>
        <LivePlayer handle={handle} streamId={streamId} />
      </div>
      {ottSurfaceLive("chat") ? <LiveChat handle={handle} streamId={streamId} /> : null}
    </main>
  );
}
