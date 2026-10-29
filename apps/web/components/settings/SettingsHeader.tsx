"use client";

import * as React from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { withoutHiddenSso } from "@/lib/sso-availability";

// MN7a: the SSO tab is left out until real SSO ships (lib/sso-availability).
const TABS = withoutHiddenSso([
  { href: "/settings/team", label: "Team" },
  { href: "/settings/billing", label: "Billing" },
  { href: "/settings/sso", label: "SSO & SCIM" },
  { href: "/settings/audit", label: "Audit log" },
  { href: "/account/api-keys", label: "API keys" },
  { href: "/settings/integrations", label: "Integrations" },
  { href: "/settings/seo", label: "SEO" },
  { href: "/settings/ad-campaigns", label: "Ad campaigns" },
  { href: "/settings/provider-keys", label: "Provider keys" },
  { href: "/settings/scheduler", label: "Buffer / Typefully" },
  { href: "/settings/privacy", label: "Privacy" },
] as const);

export interface SettingsHeaderProps {
  /** The active tab's href, to highlight it. */
  active: string;
}

/** Shared app top bar + tab strip for the workspace settings surfaces. */
export function SettingsHeader({ active }: Readonly<SettingsHeaderProps>) {
  return (
    <AppTopBar>
      <nav className="container flex gap-1 overflow-x-auto pb-2" aria-label="Settings">
        {TABS.map((tab) => {
          const isActive = tab.href === active;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "shrink-0 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-secondary text-foreground"
                  : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
              )}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
    </AppTopBar>
  );
}
