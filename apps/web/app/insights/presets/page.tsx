import type { Metadata } from "next";
import { Package } from "lucide-react";
import { PresetsView } from "@/components/presets/PresetsView";

export const metadata: Metadata = {
  title: "Brand kits",
  description:
    "Save and reuse your favourite avatar, voice, layout, caption, and music combinations as brand kits to pre-fill every new reel.",
};

/** Growth › Brand kits — save and apply reusable reel presets. */
export default function InsightsPresetsPage() {
  return (
    <>
      <div className="mb-6 max-w-2xl">
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Package className="size-6 text-primary" aria-hidden />
          Brand kits
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Save your go-to avatar, voice, layout, caption style, and background
          music as a reusable kit. Apply a kit to pre-fill a new reel in one
          click instead of rebuilding your look every time.
        </p>
      </div>

      <PresetsView />
    </>
  );
}
