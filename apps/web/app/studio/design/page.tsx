import type { Metadata } from "next";
import { PenTool } from "lucide-react";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { DesignHome } from "@/components/design/DesignHome";

export const metadata: Metadata = {
  title: "Design Studio",
  description: "Static on-brand posts, stories, banners, carousels and app store screenshots.",
  robots: { index: false, follow: false },
};

/** Design Studio: prompt + brand kit -> layouts -> on-canvas editor -> PNG export -> schedule. */
export default function DesignStudioPage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        <div className="mb-2 flex items-center gap-2">
          <PenTool className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Design Studio</h1>
        </div>
        <p className="mb-6 max-w-3xl text-sm text-muted-foreground">
          Describe a post and pick a brand kit. You get a few layouts in your colours, fonts and logo, then edit text,
          images and shapes on the canvas, export PNGs to your library and queue them for posting.
        </p>
        <DesignHome />
      </section>
    </main>
  );
}
