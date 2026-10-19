import type { Metadata } from "next";
import Link from "next/link";
import { MyCharacters } from "@/src/features/my-characters";
import { NewThisWeek } from "@/src/features/preset-drops";
import { PresetShelf, PresetUse } from "@/src/features/presets-shelf";

export const metadata: Metadata = {
  title: "Presets",
  description: "Camera moves, looks and effects for your reels. Tap one, add your topic or link, and see the price before you make it.",
  alternates: { canonical: "/presets-gallery" },
};

type PresetsSearchParams = {
  use?: string | string[];
  image?: string | string[];
  characters?: string | string[];
};

function first(value: string | string[] | undefined): string {
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

/** `/presets-gallery` (MH2): the public preset shelf; `?use=<id>` opens one preset. */
export default async function PresetsGalleryPage({
  searchParams,
}: Readonly<{ searchParams: Promise<PresetsSearchParams> }>) {
  const query = await searchParams;
  const use = first(query.use).slice(0, 64);
  const characters = first(query.characters) === "1";
  return (
    <div className="container py-12 lg:py-16">
      <h1 className="mb-2 text-3xl font-bold tracking-tight">{characters ? "My characters and brands" : "Presets"}</h1>
      <p className="mb-8 text-muted-foreground">
        {characters
          ? "Create a character or brand kit once and use it in every preset."
          : "Tap a preset, add your topic or link, and make it."}{" "}
        <Link className="underline underline-offset-4" href={characters ? "/presets-gallery" : "/presets-gallery?characters=1"}>
          {characters ? "Back to presets" : "My characters and brands"}
        </Link>
      </p>
      {characters ? (
        <MyCharacters />
      ) : use ? (
        <PresetUse presetId={use} imageKey={first(query.image).slice(0, 512)} />
      ) : (
        <>
          <NewThisWeek />
          <PresetShelf />
        </>
      )}
    </div>
  );
}
