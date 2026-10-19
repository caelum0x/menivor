"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Boxes, Coins, Sparkles } from "lucide-react";

const TABS = [
  { href: "/media/playground", label: "Playground", icon: Sparkles },
  { href: "/media/models", label: "Models", icon: Boxes },
  { href: "/media/usage", label: "Credits & usage", icon: Coins },
];

/** Shared sub-nav for the media-gateway pages (playground / models / usage). */
export function MediaGatewayNav() {
  const pathname = usePathname();
  return (
    <nav className="mb-6 flex flex-wrap gap-2">
      {TABS.map(({ href, label, icon: Icon }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            className={[
              "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:text-foreground",
            ].join(" ")}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
