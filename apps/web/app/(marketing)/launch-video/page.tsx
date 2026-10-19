import type { Metadata } from "next";
import { LaunchVideoClient } from "./LaunchVideoClient";

export const metadata: Metadata = {
  title: "Launch video for your app",
  description: "Turn your app's link into three launch reels with a hook-first script, voiceover and captions.",
  alternates: { canonical: "/launch-video" },
  robots: { index: false, follow: true },
};

type LaunchVideoSearchParams = {
  app_url?: string | string[];
  app_name?: string | string[];
  source?: string | string[];
};

function first(value: string | string[] | undefined): string {
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

/**
 * `/launch-video` (MR8): where Scribase (and later Rally) send a user with a
 * partner token in the URL fragment. The page never asks for the token; it
 * reads it, asks the user to sign in to Menivor with their own email, then
 * pre-fills the create flow with the app's link.
 */
export default async function LaunchVideoPage({
  searchParams,
}: Readonly<{ searchParams: Promise<LaunchVideoSearchParams> }>) {
  const query = await searchParams;
  return (
    <div className="container max-w-2xl py-16 lg:py-24">
      <LaunchVideoClient
        appUrl={first(query.app_url).slice(0, 500)}
        appName={first(query.app_name).slice(0, 80)}
        source={first(query.source) === "rally" ? "rally" : "scribase"}
      />
    </div>
  );
}
