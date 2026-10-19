"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";

import { PresetsView } from "@/components/presets/PresetsView";
import { BrandKitImport } from "./BrandKitImport";

/**
 * Brand kits page body: brand import on top, the saved kits below. The saved
 * kits list is remounted after an import so it re-fetches and shows the new or
 * updated kit.
 *
 * A Rally deep link (`?rally_brand_kit=<share link or token>`) pre-selects the
 * Rally source with the token filled in; nothing is imported until the user
 * confirms.
 */
export function BrandKitsWorkspace() {
  return (
    <React.Suspense fallback={<PresetsView />}>
      <BrandKitsWorkspaceInner />
    </React.Suspense>
  );
}

function BrandKitsWorkspaceInner() {
  const params = useSearchParams();
  const rallyShare = (params?.get("rally_brand_kit") ?? "").slice(0, 2048);
  const website = (params?.get("brand_url") ?? "").slice(0, 2048);
  const [version, setVersion] = React.useState(0);

  return (
    <div className="space-y-8">
      <BrandKitImport
        initialSource={rallyShare ? "rally" : "website"}
        initialValue={rallyShare || website}
        onImported={() => setVersion((v) => v + 1)}
      />
      <PresetsView key={version} />
    </div>
  );
}
