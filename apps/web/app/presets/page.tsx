import type { Metadata } from "next";
import Link from "next/link";
import { Plus } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { BrandKitsWorkspace } from "@/src/features/brand/BrandKitsWorkspace";
import { MenivorMark } from "@/components/brand/MenivorMark";

export const metadata: Metadata = {
  title: "Brand kits",
  description:
    "Save and reuse your favourite avatar, voice, layout, caption, and music combinations as brand kits to pre-fill every new reel.",
};

export default function PresetsPage() {
  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link
            href="/reels"
            className="flex items-center gap-2 font-semibold"
          >
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <div className="flex items-center gap-3">
            <Button asChild size="sm">
              <Link href="/new">
                <Plus className="size-4" aria-hidden /> New reel
              </Link>
            </Button>
            <UserButton />
          </div>
        </div>
      </header>

      <section className="container py-10">
        <div className="mb-8 max-w-2xl">
          <h1 className="text-3xl font-bold tracking-tight">Brand kits</h1>
          <p className="mt-2 text-muted-foreground">
            Save your go-to avatar, voice, layout, caption style, and background
            music as a reusable kit. Apply a kit to pre-fill a new reel in one
            click instead of rebuilding your look every time.
          </p>
        </div>

        <BrandKitsWorkspace />
      </section>
    </main>
  );
}
