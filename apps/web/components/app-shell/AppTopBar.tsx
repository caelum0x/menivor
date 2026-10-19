"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { SignedIn } from "@/components/auth/clerk-safe";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { AdminNavLink } from "@/components/admin/AdminNavLink";
import { AuthControls } from "./AuthControls";
import { PrimaryNavBar, PrimaryTabBar } from "./PrimaryNav";
import { MenivorMark } from "@/components/brand/MenivorMark";

interface AppTopBarProps {
  /** Optional slot rendered before the account controls (e.g. credits pill). */
  readonly extra?: ReactNode;
  /** Optional row rendered under the bar (e.g. a section tab strip). */
  readonly children?: ReactNode;
}

/**
 * The shared app header: the brand (back to Home), the five icon-only
 * destinations (Home, Create, Results, Settings, More), notifications and
 * the account menu. On phones the destinations move to a bottom tab bar.
 */
export function AppTopBar({ extra, children }: AppTopBarProps) {
  return (
    <>
      <header className="glass-bar sticky top-0 z-40 border-b">
        <div className="container relative flex h-16 items-center justify-between gap-3">
          <Link
            href="/reels"
            aria-label="Menivor home"
            className="flex items-center gap-2 font-semibold"
          >
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <PrimaryNavBar />
          <div className="flex items-center gap-2">
            {extra}
            <AdminNavLink />
            <SignedIn>
              <NotificationBell />
            </SignedIn>
            <AuthControls />
          </div>
        </div>
        {children}
      </header>
      <PrimaryTabBar />
    </>
  );
}
