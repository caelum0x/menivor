import type { Metadata } from "next";
import Link from "next/link";
import { Plus } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { BrollStudio } from "@/src/features/broll-studio";
import { MenivorMark } from "@/components/brand/MenivorMark";

export const metadata: Metadata = {
  title: "AI B-roll Studio",
  description:
    "Generate short AI motion clips from a text prompt and drop them into a reel as intro/outro B-roll. Each clip renders on a GPU in about 30–120 seconds.",
};

export default function BrollStudioPage() {
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
          <h1 className="text-3xl font-bold tracking-tight">AI B-roll Studio</h1>
          <p className="mt-2 text-muted-foreground">
            Describe a shot and generate a short AI motion clip. When it&apos;s
            ready, attach it directly to a new reel on the{" "}
            <Link href="/new" className="underline underline-offset-4">
              New reel
            </Link>{" "}
            form.
          </p>
        </div>

        <BrollStudio />
      </section>
    </main>
  );
}
