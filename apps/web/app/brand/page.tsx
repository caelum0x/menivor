import type { Metadata } from "next";
import Link from "next/link";
import { Plus, Stamp } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { BrandEditor } from "@/components/brand/BrandEditor";
import { MenivorMark } from "@/components/brand/MenivorMark";

export const metadata: Metadata = {
  title: "Brand Watermark",
  description:
    "Upload a transparent PNG logo and overlay it on every reel at a chosen corner and opacity. Applied by default in the compose stage; individual jobs can override or disable it.",
};

export default function BrandPage() {
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
        <div className="mx-auto max-w-4xl">
          <div className="mb-8 max-w-2xl">
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <Stamp className="size-7 text-primary" aria-hidden />
              Brand Watermark
            </h1>
            <p className="mt-2 text-muted-foreground">
              Upload a transparent PNG logo and choose where it sits on your
              reels. Once saved, it&apos;s overlaid on every new reel by default —
              individual jobs can still override or turn it off.
            </p>
          </div>

          <BrandEditor />
        </div>
      </section>
    </main>
  );
}
