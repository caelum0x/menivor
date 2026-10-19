import { UserButton } from "@/components/auth/clerk-safe";
import { Clapperboard } from "lucide-react";

import { MotionStudio } from "@/src/features/motion/MotionStudio";

/** Motion / effects studio route — browse, compile, and reuse camera moves. */
export default function MotionPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clapperboard className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Motion &amp; effects studio</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <p className="mb-6 text-sm text-muted-foreground">
        Browse the camera-move catalog, tune intensity, and compile a deterministic
        motion plan the render worker consumes — filter, model, or hybrid moves.
      </p>
      <MotionStudio />
    </main>
  );
}
