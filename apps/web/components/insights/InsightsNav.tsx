"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, Gift, LineChart, Package } from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  readonly href: string;
  readonly label: string;
  readonly icon: React.ComponentType<{ className?: string }>;
}

/** The Growth-area sub-navigation shown across every /insights surface. */
const ITEMS: readonly NavItem[] = [
  { href: "/insights", label: "Overview", icon: BarChart3 },
  { href: "/insights/analytics", label: "Analytics", icon: LineChart },
  { href: "/insights/referral", label: "Referrals", icon: Gift },
  { href: "/insights/presets", label: "Brand kits", icon: Package },
];

/**
 * Tab-style sub-navigation for the Growth center. Highlights the current route
 * (exact match for the overview, prefix match for the deeper sections) so the
 * disconnected analytics / referral / preset pages read as one area.
 */
export function InsightsNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Growth sections"
      className="mb-6 flex flex-wrap gap-1 border-b border-border"
    >
      {ITEMS.map((item) => {
        const isActive =
          item.href === "/insights"
            ? pathname === "/insights"
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
