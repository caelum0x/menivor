import { getPreset, type CaptionStyle } from "@reelforge/caption-engine";

/**
 * "Anatomy of a Menivor caption" — CSS specimens of the four real burned-in
 * caption presets from `@reelforge/caption-engine`, the registry both the API
 * and the render worker build ASS subtitles from. Colors, casing, weights, and
 * word grouping are read from the presets themselves; only the typeface is a
 * web-safe approximation of the ASS font. Nothing here is invented.
 *
 * Anchored at #demo: this live section is the product demo while no recorded
 * walkthrough exists — it shows the exact output styling a render produces.
 */

interface PresetSpecimen {
  readonly key: string;
  readonly words: readonly string[];
  /** Index of the word shown in the preset's highlight color. */
  readonly highlightIndex: number;
}

const SPECIMENS: readonly PresetSpecimen[] = [
  { key: "hormozi", words: ["every", "word", "hits"], highlightIndex: 1 },
  {
    key: "karaoke-classic",
    words: ["follow", "along", "line", "by", "line"],
    highlightIndex: 2,
  },
  {
    key: "minimal-top-label",
    words: ["quiet", "labels", "up", "top"],
    highlightIndex: 1,
  },
  {
    key: "brainrot-popin",
    words: ["pop", "in", "loud"],
    highlightIndex: 0,
  },
];

/** ASS numpad alignment → human position label. */
function alignmentLabel(alignment: number): string {
  if (alignment >= 7) return "top";
  if (alignment >= 4) return "middle";
  return "bottom";
}

/** Approximate the preset's ASS outline + shadow as layered CSS text-shadow. */
function specimenShadow(style: CaptionStyle): string {
  const o = Math.max(1, Math.round(style.outline / 2));
  const layers = [
    `-${o}px 0 ${style.outline_hex}`,
    `${o}px 0 ${style.outline_hex}`,
    `0 -${o}px ${style.outline_hex}`,
    `0 ${o}px ${style.outline_hex}`,
  ];
  if (style.shadow > 0) {
    layers.push(`${style.shadow}px ${style.shadow}px 2px rgba(0, 0, 0, 0.6)`);
  }
  return layers.join(", ");
}

function SpecimenCard({ specimen }: { readonly specimen: PresetSpecimen }) {
  const style = getPreset(specimen.key);
  const heavy = style.bold;

  return (
    <div className="flex flex-col border-t border-border pt-6">
      <p className="kicker text-muted-foreground">{specimen.key}</p>

      <div className="mt-4 flex min-h-32 items-center justify-center rounded-xl border border-white/[0.08] bg-black px-4 py-8 shadow-[inset_0_1px_0_hsl(0_0%_100%/0.05),0_16px_40px_-20px_hsl(0_0%_0%/0.8)]">
        <p
          className={`select-none text-center text-2xl leading-tight ${
            heavy ? "font-display font-bold" : "font-sans font-medium"
          }`}
          style={{ textShadow: specimenShadow(style) }}
          aria-label={specimen.words.join(" ")}
        >
          {specimen.words.map((word, index) => (
            <span
              key={word + String(index)}
              style={{
                color:
                  index === specimen.highlightIndex
                    ? style.highlight_hex
                    : style.primary_hex,
              }}
            >
              {style.uppercase ? word.toUpperCase() : word}
              {index < specimen.words.length - 1 ? " " : ""}
            </span>
          ))}
        </p>
      </div>

      <p className="kicker mt-3 text-muted-foreground">
        {style.font} &middot; {style.size}px &middot; {style.words_per_group}
        &nbsp;words/group &middot; {alignmentLabel(style.alignment)}
      </p>
    </div>
  );
}

export function CaptionPresets() {
  return (
    <section id="demo" className="scroll-mt-20 border-b border-border">
      <div className="container py-20">
        <div className="mb-12 max-w-2xl">
          <p className="kicker text-muted-foreground">burned-in captions</p>
          <h2 className="mt-4 text-display font-bold">
            Four caption styles, straight from the render engine.
          </h2>
          <p className="mt-4 text-pretty leading-relaxed text-muted-foreground">
            These specimens are drawn from the same preset registry the render
            worker uses to build ASS subtitles — word-level timing from speech
            recognition, byte-identical output across the TypeScript and Python
            engines. What you see here is the styling your reel ships with.
          </p>
        </div>

        <div className="grid gap-x-10 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
          {SPECIMENS.map((specimen) => (
            <SpecimenCard key={specimen.key} specimen={specimen} />
          ))}
        </div>
      </div>
    </section>
  );
}
