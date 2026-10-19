import type { Metadata } from "next";

import { ShowcaseWall } from "@/components/marketing/showcase/ShowcaseWall";
import { ShowcaseNote } from "@/components/marketing/showcase/ShowcaseNote";
import { showcaseLayout } from "@/lib/styles/showcase";
import { ShowcasePage } from "@/src/features/showcase/ShowcasePage";

export const metadata: Metadata = {
  title: "Showcase",
  description:
    "Watch real reels Menivor has rendered, then browse the viral shot-template gallery and your own completed reels. Templates are pulled from the real catalog (GET /templates); your reels come from GET /jobs filtered to completed renders.",
};

/**
 * Showcase — real rendered reels, then the template catalog and completed
 * reels.
 *
 * The real-reels wall and the templates section are always visible (no auth
 * required): every reel is an actual render from this pipeline (see
 * `lib/styles/showcase.ts`), not stock marketing footage, and `ShowcaseNote`
 * says exactly how each one was made. The completed-reels section below it
 * requires sign-in and is labelled as the caller's own jobs, not a publicly
 * curated feed (no public showcase endpoint exists today).
 */
export default function ShowcaseRoute() {
  const { groups } = showcaseLayout();
  return (
    <>
      <div className="bg-black">
        <div className="container pb-0 pt-12 lg:pt-16">
          <p className="kicker text-muted-foreground">Showcase</p>
          <h1 className="mt-4 max-w-2xl text-balance text-display font-bold">
            Real reels, not mockups.
          </h1>
          <p className="mt-3 max-w-xl text-pretty text-muted-foreground">
            Every tile below rendered through Menivor&apos;s own pipeline: a typed
            script, a neural voice and word-by-word captions. Hover a reel to
            make yours in the same style.
          </p>
        </div>
        {groups.map((group) => (
          <ShowcaseWall
            key={group.id}
            id={group.id}
            title={group.title}
            subline={group.subline}
            reels={group.reels}
          />
        ))}
        <ShowcaseNote />
      </div>
      <ShowcasePage />
    </>
  );
}
