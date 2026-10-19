import * as React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { Sparkles, Wand2 } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";

import { Button } from "@/components/ui/button";
import { CreateCompose } from "@/src/features/create-compose";

export const metadata: Metadata = {
  title: "Start from a template",
  description:
    "Compile a ready-to-post 9:16 reel from a genre template — pick a format, set your inputs, and render.",
};

/**
 * `/create/templates` — template-driven compose flow. Choose a genre template, fill its
 * inputs, and compile a real render job. For the full step-by-step upload flow,
 * the guided wizard lives at `/new`.
 */
export default function CreatePage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Start from a template</h1>
        </div>
        <div className="flex items-center gap-3">
          <Button asChild variant="outline" size="sm">
            <Link href="/new">
              <Wand2 className="mr-1 h-4 w-4" aria-hidden /> Guided wizard
            </Link>
          </Button>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <React.Suspense
        fallback={
          <p className="text-sm text-muted-foreground">Loading…</p>
        }
      >
        <CreateCompose />
      </React.Suspense>
    </main>
  );
}
