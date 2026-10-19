"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavItem {
  href: string;
  label: string;
  /** Match `pathname === href` exactly, or `pathname.startsWith(href)`. */
  exact?: boolean;
}

const ITEMS: readonly NavItem[] = [
  { href: "/account", label: "Overview", exact: true },
  { href: "/wallet", label: "Wallet" },
  { href: "/billing", label: "Plan & billing" },
  { href: "/workspace", label: "Workspaces" },
  { href: "/referral", label: "Referrals" },
  { href: "/notifications", label: "Notifications" },
  { href: "/connections", label: "Connections", exact: true },
  { href: "/connections/queue", label: "Publish queue" },
  { href: "/autopost", label: "Autopost" },
  { href: "/account/api-keys", label: "API keys" },
  { href: "/usage", label: "Usage" },
  { href: "/settings/privacy", label: "Privacy" },
  { href: "/developer", label: "Developer" },
];

function isActive(pathname: string, item: NavItem): boolean {
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

/**
 * Horizontal section navigation shared across the Account / Connections /
 * Workspace surfaces so a signed-in user can move between them. Highlights the
 * current route via {@link usePathname}. Purely presentational.
 */
export function AccountNav() {
  const pathname = usePathname() ?? "";

  return (
    <nav
      aria-label="Account sections"
      className="mb-8 flex flex-wrap gap-1 border-b border-border"
    >
      {ITEMS.map((item) => {
        const active = isActive(pathname, item);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={
              active
                ? "-mb-px border-b-2 border-primary px-3 py-2 text-sm font-medium text-foreground"
                : "-mb-px border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            }
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
