import { UserButton } from "@/components/auth/clerk-safe";
import { LayoutGrid } from "lucide-react";

import { StudioHub } from "@/src/features/studio/StudioHub";

/** Studio hub route — one place to reach every creation + growth tool. */
export default function StudioPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <LayoutGrid className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Studio</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <p className="mb-6 text-sm text-muted-foreground">
        Everything you need to make, grow and monetize short-form — templates, characters, film, render,
        trends, marketplace, publishing and your API gateway.
      </p>
      <StudioHub />
    </main>
  );
}
