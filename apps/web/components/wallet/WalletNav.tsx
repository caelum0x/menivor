"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Coins,
  CreditCard,
  ReceiptText,
  SlidersHorizontal,
  Wallet,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  readonly href: string;
  readonly label: string;
  readonly icon: React.ComponentType<{ className?: string }>;
}

/** The Wallet-area sub-navigation shown across every /wallet surface. */
const ITEMS: readonly NavItem[] = [
  { href: "/wallet", label: "Overview", icon: Wallet },
  { href: "/wallet/activity", label: "Activity", icon: ReceiptText },
  { href: "/wallet/plans", label: "Credit packs", icon: Coins },
  { href: "/spend", label: "Spend controls", icon: SlidersHorizontal },
  { href: "/billing", label: "Workspace plan", icon: CreditCard },
];

/**
 * Tab-style sub-navigation for the Wallet area. Highlights the current route
 * (exact match for the overview, prefix match for the deeper sections).
 */
export function WalletNav() {
  // `usePathname()` is typed non-null in app router pages but CAN be null in
  // isolated renders (tests, error boundaries) — degrade to "no active tab".
  const pathname = usePathname() ?? "";

  return (
    <nav
      aria-label="Wallet sections"
      className="mb-6 flex flex-wrap gap-1 border-b border-border"
    >
      {ITEMS.map((item) => {
        const isActive =
          item.href === "/wallet"
            ? pathname === "/wallet"
            : pathname === item.href || pathname.startsWith(`${item.href}/`);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              isActive
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-4" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
