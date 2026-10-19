import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { Storefront } from "@/src/features/ott-player/Storefront";
import { getStorefront } from "@/src/features/ott-player/api";
import { ottStorefrontLive, ottSurfaceLive } from "@/src/features/ott-player/flags";
import { ViewerAccount } from "@/src/features/ott-auth";
import { Offers } from "@/src/features/ott-checkout";
import { LiveNow } from "@/src/features/ott-live-chat";
import { SearchBox } from "@/src/features/ott-discovery";

type Params = Promise<{ handle: string }>;

export async function generateMetadata({ params }: Readonly<{ params: Params }>): Promise<Metadata> {
  if (!ottStorefrontLive()) return {};
  const { handle } = await params;
  const data = await getStorefront(handle);
  return data ? { title: data.title, description: data.tagline || `Watch ${data.title}` } : {};
}

export default async function ChannelPage({ params }: Readonly<{ params: Params }>) {
  if (!ottStorefrontLive()) notFound();
  const { handle } = await params;
  const country = (await headers()).get("cf-ipcountry");
  const data = await getStorefront(handle, country);
  if (!data) notFound();
  return (
    <>
      {ottSurfaceLive("viewers") ? <ViewerAccount handle={data.handle} /> : null}
      {ottSurfaceLive("commerce") ? <Offers handle={data.handle} /> : null}
      {ottSurfaceLive("live") ? <LiveNow handle={data.handle} /> : null}
      {ottSurfaceLive("discovery") ? <SearchBox handle={data.handle} /> : null}
      <Storefront data={data} />
    </>
  );
}
