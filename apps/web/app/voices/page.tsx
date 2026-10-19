import type { Metadata } from "next";
import Link from "next/link";
import { Plus } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { VoiceManager } from "@/components/voices/VoiceManager";
import { MenivorMark } from "@/components/brand/MenivorMark";

export const metadata: Metadata = {
  title: "Brand Voice",
  description:
    "Clone your own voice from a short sample and use it as the narrator on any reel. Recording requires your explicit consent that you own or are authorized to use the voice.",
};

export default function VoicesPage() {
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
          <h1 className="text-3xl font-bold tracking-tight">Brand Voice</h1>
          <p className="mt-2 text-muted-foreground">
            Clone your own voice from a short 30-60 second sample, then choose it
            as the narrator on any reel. You must confirm you own or are
            authorized to use the voice before cloning.
          </p>
        </div>

        <VoiceManager />
      </section>
    </main>
  );
}
