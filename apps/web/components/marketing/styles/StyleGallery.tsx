import Link from "next/link";
import { allocateStyleGallery } from "@/lib/styles/showcase";
import { ShowcaseTile } from "@/components/marketing/showcase/ShowcaseTile";
import { UseStyleButton } from "./StylePick";

/**
 * "Pick a style": one card per format that has a real showcase reel. The card
 * plays that reel (muted, only while visible) and one click preselects the
 * style in the paste box.
 */
export function StyleGallery({ heading = true }: Readonly<{ heading?: boolean }>) {
  const { cards } = allocateStyleGallery();
  return (
    <section id="styles" className="scroll-mt-20 border-b border-white/[0.06]">
      <div className="container py-16 lg:py-20">
        {heading ? (
          <div className="mb-10 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="max-w-xl">
              <p className="kicker text-muted-foreground">Pick a style</p>
              <h2 className="mt-3 text-display font-bold">Formats that already work on TikTok</h2>
            </div>
            <Link href="/styles" className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground">
              All styles
            </Link>
          </div>
        ) : null}
        <ul className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 lg:grid-cols-4">
          {cards.map(({ style, reel }) => (
            <li key={style.id} className="flex flex-col gap-3">
              <ShowcaseTile reel={reel} />
              <div className="flex flex-1 flex-col gap-2 px-1">
                <h3 className="text-sm font-semibold text-foreground sm:text-base">{style.label}</h3>
                <p className="line-clamp-3 text-xs leading-relaxed text-muted-foreground sm:text-sm">
                  {style.blurb}
                </p>
                <div className="mt-auto pt-1">
                  <UseStyleButton styleId={style.id} className="w-full" />
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
