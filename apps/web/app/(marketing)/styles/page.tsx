import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StyleGallery } from "@/components/marketing/styles/StyleGallery";
import { ShowcaseWall } from "@/components/marketing/showcase/ShowcaseWall";
import { StylePickProvider } from "@/components/marketing/styles/StylePick";
import { REEL_STYLES } from "@/lib/styles/catalog";
import { allocateStyleGallery } from "@/lib/styles/showcase";
import { VARIANT_COUNT } from "@/src/features/create-compose/one-flow/plan";

export const metadata: Metadata = {
  title: "Reel styles: gameplay split, meme hooks, anime and more",
  description:
    "Pick a short-form style and paste a link: gameplay split-screen, meme-caption hooks, original anime-style scenes, satisfying split, POV text, before and after, story time and a cartoon narrator.",
  alternates: { canonical: "/styles" },
};

const LOOP_NOTES: readonly { readonly title: string; readonly body: string }[] = [
  {
    title: "Original footage only",
    body: "Gameplay parkour and satisfying loops are rendered by us from our own code or come from licensed stock video. No captured game footage, ripped clips or library sounds.",
  },
  {
    title: "Anime style, not anime clips",
    body: "Anime-style scenes are original AI illustrations generated for your reel. We never name or imitate a show, studio or character.",
  },
  {
    title: "Meme structure, your words",
    body: "Meme hooks reuse only a text pattern people recognize, written from your own page. The visuals are yours and ours.",
  },
];

/**
 * `/styles`: every one-click style that has a real showcase reel and a "Use this style" link into the create box, plus how each
 * format stays rights-clean.
 */
export default function StylesPage() {
  const { rest } = allocateStyleGallery();
  return (
    <>
      <section className="border-b border-white/[0.06]">
        <div className="container py-16 lg:py-20">
          <p className="kicker text-muted-foreground">Styles</p>
          <h1 className="mt-4 max-w-3xl text-balance text-display-lg font-bold">
            {REEL_STYLES.length} formats. One click each.
          </h1>
          <p className="mt-5 max-w-xl text-pretty text-lg leading-relaxed text-muted-foreground">
            Paste your link, pick a style, and Menivor writes, voices, captions and renders
            three versions with different opening hooks.
          </p>
          <div className="mt-8">
            <Button asChild size="lg">
              <Link href="/create" data-copy-source="src/features/create-compose/one-flow/plan.ts">
                {/* copy-source: src/features/create-compose/one-flow/plan.ts VARIANT_COUNT */}
                Make {VARIANT_COUNT} reels <ArrowRight className="size-4" aria-hidden />
              </Link>
            </Button>
          </div>
        </div>
      </section>
      <StylePickProvider>
        <StyleGallery heading={false} />
        <ShowcaseWall
          id="more"
          title="More reels"
          subline="Every other showcase reel, one niche each. Hover a reel for its style."
          reels={rest}
        />
      </StylePickProvider>
      <section>
        <div className="container py-16">
          <h2 className="text-display font-bold">Safe to post</h2>
          <ul className="mt-8 grid gap-4 md:grid-cols-3">
            {LOOP_NOTES.map((note) => (
              <li key={note.title} className="glass-subtle rounded-2xl p-5">
                <h3 className="text-base font-semibold text-foreground">{note.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{note.body}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </>
  );
}
