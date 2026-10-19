import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { OttStudio } from "@/src/features/ott-cms";
import { ottCmsLive } from "@/src/features/ott-player/flags";

export const metadata: Metadata = {
  title: "Channel studio",
  robots: { index: false, follow: false },
};

/** The creator's channel studio; not found until the channel studio is live. */
export default function OttStudioPage() {
  if (!ottCmsLive()) notFound();
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="mb-2 text-2xl font-semibold">Channel studio</h1>
      <p className="mb-6 text-sm text-muted-foreground">Your finished reels become your own channel in one press.</p>
      <OttStudio />
    </main>
  );
}
