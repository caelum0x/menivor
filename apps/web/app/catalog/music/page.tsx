import type { Metadata } from "next";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { MusicBrowser } from "@/components/catalog/MusicBrowser";

export const metadata: Metadata = {
  title: "Music library",
  description:
    "Browse background-music tracks you can drop onto any reel, with track ids and durations.",
};

/** Browse the background-music catalog (GET /catalog/music). */
export default function MusicPage() {
  return (
    <CatalogShell
      title="Music library"
      description="Background-music tracks for your reels. Search by name or file and copy the track id to use it."
      backHref="/catalog"
      backLabel="Catalog"
    >
      <MusicBrowser />
    </CatalogShell>
  );
}
