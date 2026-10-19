import * as React from "react";
import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { InsightsSectionNav } from "@/src/features/insights/InsightsSectionNav";
import { MenivorMark } from "@/components/brand/MenivorMark";

/**
 * Growth center shell. Provides the shared ReelForge header and the tab-style
 * sub-navigation (Overview / Analytics / Referrals / Brand kits) for every
 * `/insights/*` surface so the four Growth pages read as one connected area.
 * Each child page owns its own title, loading, empty, and error states.
 */
export default function InsightsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <div className="flex items-center gap-3">
            <Button asChild variant="outline" size="sm">
              <Link href="/reels">Your reels</Link>
            </Button>
            <UserButton />
          </div>
        </div>
      </header>

      <section className="container py-8">
        <InsightsSectionNav />
        {children}
      </section>
    </main>
  );
}
