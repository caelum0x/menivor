import type { Metadata } from "next";
import Link from "next/link";
import { Plus } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { AvatarManager } from "@/components/avatars/AvatarManager";
import { MenivorMark } from "@/components/brand/MenivorMark";

export const metadata: Metadata = {
  title: "Custom Avatars",
  description:
    "Turn a selfie into a talking-photo avatar that lip-syncs your reel's narration, then pick it as the presenter on any reel. Only upload a photo of yourself or one you are authorized to use.",
};

export default function AvatarsPage() {
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
          <h1 className="text-3xl font-bold tracking-tight">Custom Avatars</h1>
          <p className="mt-2 text-muted-foreground">
            Turn a selfie into a talking-photo avatar that lip-syncs your reel&apos;s
            narration, then choose it as the presenter on any reel. Only upload a
            photo of yourself or one you are authorized to use.
          </p>
        </div>

        <AvatarManager />
      </section>
    </main>
  );
}
