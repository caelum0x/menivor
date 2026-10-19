import type { ShowcaseMedia } from "@/lib/styles/showcase";
import { ShowcaseTile } from "./ShowcaseTile";
import { PasteLinkButton } from "./PasteLinkButton";

// Small height changes between tiles give the masonry its stagger (the crop
// stays inside the reel's safe area, so hooks and captions are never cut).
const RHYTHM = ["aspect-[9/16]", "aspect-[3/5]", "aspect-[9/16]", "aspect-[5/8]"] as const;

/**
 * One themed wall: an uppercase title, a one-line subline, the "Paste a link"
 * action, and a dense masonry of moving reels (2 to 5 columns). Every tile is
 * a different reel with its own opening line.
 */
export function ShowcaseWall({
  id,
  title,
  subline,
  reels: ownReels,
  gallery = [],
}: Readonly<{
  id: string;
  title: string;
  subline: string;
  reels: readonly ShowcaseMedia[];
  /** Wave P PM1.3: owner-approved gallery items (`galleryWallMedia`), at most six. */
  gallery?: readonly ShowcaseMedia[];
}>) {
  const reels = [...ownReels, ...gallery.slice(0, 6)];
  if (reels.length === 0) return null;
  return (
    <section id={`reels-${id}`} aria-labelledby={`reels-${id}-title`} className="scroll-mt-20">
      <div className="mx-auto max-w-[1600px] px-3 py-10 sm:px-4 lg:py-14">
        <div className="mb-5 flex flex-col gap-3 px-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2
              id={`reels-${id}-title`}
              className="font-display text-2xl font-bold uppercase leading-none tracking-tight text-primary sm:text-4xl"
            >
              {title}
            </h2>
            <p className="mt-2 text-sm text-muted-foreground sm:text-base">{subline}</p>
          </div>
          <PasteLinkButton className="self-start sm:self-auto" />
        </div>
        <ul className="columns-2 gap-2 sm:columns-3 lg:columns-4 xl:columns-5">
          {reels.map((reel, index) => (
            <li key={reel.key} className="mb-2 break-inside-avoid">
              <ShowcaseTile reel={reel} aspectClass={RHYTHM[index % RHYTHM.length]} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
