"use client";

import * as React from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { MenivorMark } from "@/components/brand/MenivorMark";

/** Shared top bar for the developer portal (logo home link + new-reel + account). */
export function DeveloperHeader() {
  return (
    <header className="border-b border-border">
      <div className="container flex items-center justify-between py-4">
        <Link
          href="/reels"
          className="flex items-center gap-2 font-semibold"
        >
          <MenivorMark variant="gradient" className="size-7" title="Menivor" />
        </Link>
        <div className="flex items-center gap-3">
          <Button asChild variant="outline" size="sm">
            <Link href="/reels">Your reels</Link>
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
  );
}
