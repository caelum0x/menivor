import type { Metadata } from "next";
import Link from "next/link";
import { Plus, Wand2 } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";

import { Button } from "@/components/ui/button";
import { BrollLibrary } from "@/src/features/broll-library";
import { MenivorMark } from "@/components/brand/MenivorMark";

export const metadata: Metadata = {
  title: "B-roll Library",
  description:
    "Browse, filter, and reuse your AI B-roll clips. Drop a finished clip into a new reel as its intro B-roll, or download it directly.",
};

/** B-roll Library route — browse and reuse the caller's generated AI clips. */
export default function BrollLibraryPage() {
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
            <Button asChild size="sm" variant="outline">
              <Link href="/broll">
                <Wand2 className="size-4" aria-hidden /> B-roll Studio
              </Link>
            </Button>
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
          <h1 className="text-3xl font-bold tracking-tight">B-roll Library</h1>
          <p className="mt-2 text-muted-foreground">
            Every AI B-roll clip you&apos;ve generated, in one place. Filter by
            status, use a ready clip as a reel&apos;s intro, or start
            a new one in the{" "}
            <Link href="/broll" className="underline underline-offset-4">
              B-roll Studio
            </Link>
            .
          </p>
        </div>

        <BrollLibrary />
      </section>
    </main>
  );
}
