/**
 * Local video-materials stock library — the legacy MoneyPrinterTurbo standalone
 * materials store. Lists the server's local clips/images (`GET /video_materials`)
 * and lets a creator upload a new clip or still (`POST /video_materials`). The
 * returned basename is what a render job references as a local material.
 *
 * NAV MANIFEST (routes for the integration agent to wire into navigation):
 *   { route: "/catalog/studio/stock-materials", title: "Video Materials (Stock)" }
 */

import type { ReactElement } from "react";

import { StockLibrary } from "@/components/catalog/StockLibrary";
import { listVideoMaterials, uploadVideoMaterial } from "@/lib/api";
import {
  VIDEO_MATERIAL_EXTENSIONS,
  pickVideoMaterialFromFiles,
} from "@/src/shared/media";
import { useSession } from "@/src/shared/auth";

export default function StockMaterialsScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  return (
    <StockLibrary
      token={token}
      listFiles={listVideoMaterials}
      uploadFile={uploadVideoMaterial}
      pickFile={pickVideoMaterialFromFiles}
      allowedExtensions={VIDEO_MATERIAL_EXTENSIONS}
      intro="The raw local video-materials store the render pipeline can splice in. Browse the available clips and stills or upload your own footage."
      acceptHint="MP4, MOV, AVI, FLV, MKV, JPG, JPEG or PNG."
      itemNoun="clip"
      emptyBody="No local materials have been uploaded yet. Add a clip or still to get started."
    />
  );
}
