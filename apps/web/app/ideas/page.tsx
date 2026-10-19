import type { Metadata } from "next";
import Link from "next/link";
import { Plus } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { IdeasView } from "@/components/ideas/IdeasView";
import { MenivorMark } from "@/components/brand/MenivorMark";

export const metadata: Metadata = {
  title: "Spark — AI idea engine",
  description:
    "Describe your app or niche and get ready-to-shoot viral UGC video concepts, each one click away from becoming a reel.",
};

export default function IdeasPage() {
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
          <h1 className="text-3xl font-bold tracking-tight">Spark</h1>
          <p className="mt-2 text-muted-foreground">
            Describe your app or niche and Spark hands you ready-to-shoot viral
            UGC video concepts — each with a hook, angle, script outline, and
            suggested layout and captions. Tap{" "}
            <span className="font-medium text-foreground">Make this</span> to
            drop one straight into the reel wizard, or save your favourites for
            later.
          </p>
        </div>

        <IdeasView />
      </section>
    </main>
  );
}
