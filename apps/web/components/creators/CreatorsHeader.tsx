"use client";

import Link from "next/link";
import { SignedIn, SignedOut, UserButton } from "@/components/auth/clerk-safe";
import { Crown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MenivorMark } from "@/components/brand/MenivorMark";

export interface CreatorsHeaderProps {
  /** Hide the Leaderboard nav link when already on the leaderboard page. */
  showLeaderboardLink?: boolean;
}

/**
 * Shared top bar for the PUBLIC creator surfaces (profiles + leaderboard). These
 * pages must render for logged-out visitors, so the auth control degrades to a
 * "Sign in" link when signed out (via Clerk's `SignedIn`/`SignedOut`) instead of
 * assuming a session.
 */
export function CreatorsHeader({
  showLeaderboardLink = true,
}: Readonly<CreatorsHeaderProps>) {
  return (
    <header className="border-b border-border">
      <div className="container flex items-center justify-between py-4">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <MenivorMark variant="gradient" className="size-7" title="Menivor" />
        </Link>
        <div className="flex items-center gap-3">
          {showLeaderboardLink && (
            <Button asChild variant="outline" size="sm">
              <Link href="/leaderboard">
                <Crown className="size-4" aria-hidden /> Leaderboard
              </Link>
            </Button>
          )}
          <SignedIn>
            <Button asChild variant="outline" size="sm">
              <Link href="/reels">Your reels</Link>
            </Button>
            <UserButton />
          </SignedIn>
          <SignedOut>
            <Button asChild size="sm">
              <Link href="/sign-in">Sign in</Link>
            </Button>
          </SignedOut>
        </div>
      </div>
    </header>
  );
}
