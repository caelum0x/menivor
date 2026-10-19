import { UserButton } from "@/components/auth/clerk-safe";
import { Users } from "lucide-react";

import { CharactersManager } from "@/src/features/characters/CharactersManager";

/** Character manager route — save + reuse identity-locked characters. */
export default function CharactersPage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Characters</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <p className="mb-6 text-sm text-muted-foreground">
        Save a character once and reuse it across every reel and episode — the same look, locked.
      </p>
      <CharactersManager />
    </main>
  );
}
