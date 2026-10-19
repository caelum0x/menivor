import type { Metadata } from "next";
import Link from "next/link";
import { UserPlus, Users } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";

import { Button } from "@/components/ui/button";
import { AvatarsCatalog } from "@/src/features/studio-catalog/AvatarsCatalog";

export const metadata: Metadata = {
  title: "Avatars",
  description:
    "Provider avatar catalog and identity-locked characters — choose a presenter for your next reel.",
};

/**
 * Studio sub-page: avatars and characters.
 *
 * Wired to real API endpoints:
 *   GET /avatars      — AvatarPreset rows + live provider catalog (HeyGen)
 *   GET /characters   — caller's identity-locked characters
 *
 * Avatar cards link into the reel creation flow with the avatar pre-selected.
 * Character cards link to the film planner with the character locked in.
 * The "Manage characters" button links to /characters for full CRUD.
 */
export default function StudioAvatarsPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="h-6 w-6 text-primary" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold">Avatars</h1>
            <p className="text-sm text-muted-foreground">
              Provider avatars and your identity-locked characters — pick a
              presenter or lock a character to a film.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button asChild size="sm" variant="outline">
            <Link href="/characters">
              <UserPlus className="mr-1 h-4 w-4" aria-hidden /> Characters
            </Link>
          </Button>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <AvatarsCatalog />
    </main>
  );
}
