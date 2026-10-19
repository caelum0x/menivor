/**
 * Background-music (BGM) stock library — the legacy MoneyPrinterTurbo
 * standalone music store. Lists the server's BGM files (`GET /musics`) and lets
 * a creator upload a new track (`POST /musics`). The returned basename is what a
 * render job references as its background music.
 *
 * NAV MANIFEST (routes for the integration agent to wire into navigation):
 *   { route: "/catalog/studio",              title: "Stock Libraries" }
 *   { route: "/catalog/studio/stock-music",  title: "Music Library (Stock)" }
 */

import type { ReactElement } from "react";

import { StockLibrary } from "@/components/catalog/StockLibrary";
import { listBgmFiles, uploadBgmFile } from "@/lib/api";
import { BGM_EXTENSIONS, pickBgmFileFromFiles } from "@/src/shared/media";
import { useSession } from "@/src/shared/auth";

/** Backend BGM upload hard cap (30 MB). */
const MAX_BGM_BYTES = 30 * 1024 * 1024;

export default function StockMusicScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  return (
    <StockLibrary
      token={token}
      listFiles={listBgmFiles}
      uploadFile={uploadBgmFile}
      pickFile={pickBgmFileFromFiles}
      allowedExtensions={BGM_EXTENSIONS}
      maxSizeBytes={MAX_BGM_BYTES}
      intro="The raw background-music store the render pipeline draws from. Browse what's available or upload your own track to use under a reel."
      acceptHint="MP3, M4A, AAC, WAV, FLAC, OGG, OPUS or WMA — up to 30 MB."
      itemNoun="track"
      emptyBody="No background music has been uploaded yet. Add a track to get started."
    />
  );
}
