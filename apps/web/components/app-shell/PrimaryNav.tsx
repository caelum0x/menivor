"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useIsStaff } from "@/components/admin/use-is-staff";
import { AppNavMenu } from "./AppNavMenu";
import { PRIMARY_NAV_ITEMS, isPrimaryActive, staffToolsGated } from "./nav-items";

type Placement = "top" | "bottom";

/**
 * Hover/focus tooltip for icon-only controls. The control still carries its
 * own aria-label; this is the sighted-user hint.
 */
export function IconTip({
  label,
  placement = "top",
  children,
}: Readonly<{ label: string; placement?: Placement; children: ReactNode }>) {
  return (
    <span className="group/tip relative inline-flex">
      {children}
      <span
        role="presentation"
        className={cn(
          "pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-background/95 px-2 py-1 text-xs text-foreground opacity-0 shadow-sm transition-opacity duration-150 group-hover/tip:opacity-100 group-focus-within/tip:opacity-100",
          placement === "top" ? "top-full mt-2" : "bottom-full mb-2",
        )}
      >
        {label}
      </span>
    </span>
  );
}

/**
 * WP3.2: everyone gets the five destinations. "More" (every other tool) is for
 * verified staff, or for everyone when the staff-tools gate is open.
 */
function useShowMore(): boolean {
  const { status } = useIsStaff();
  return !staffToolsGated() || status === "staff";
}

function PrimaryLinks({ placement }: Readonly<{ placement: Placement }>) {
  const pathname = usePathname() ?? "";
  const showMore = useShowMore();
  return (
    <>
      {PRIMARY_NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        const active = isPrimaryActive(pathname, item);
        return (
          <li key={item.href}>
            <IconTip label={item.label} placement={placement}>
              <Link
                href={item.href}
                aria-label={item.label}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex size-10 items-center justify-center rounded-xl transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "bg-white/[0.08] text-foreground"
                    : "text-muted-foreground hover:bg-white/[0.05] hover:text-foreground",
                )}
              >
                <Icon className="size-5" aria-hidden />
              </Link>
            </IconTip>
          </li>
        );
      })}
      {showMore && (
        <li>
          <AppNavMenu placement={placement} />
        </li>
      )}
    </>
  );
}

/** Desktop: the five destinations (plus "More" for staff) as icons in the top bar. */
export function PrimaryNavBar() {
  return (
    <nav aria-label="Main" className="hidden sm:absolute sm:left-1/2 sm:block sm:-translate-x-1/2">
      <ul className="flex items-center gap-1">
        <PrimaryLinks placement="top" />
      </ul>
    </nav>
  );
}

/** Mobile: the same destinations as a bottom tab bar. */
export function PrimaryTabBar() {
  return (
    <nav
      aria-label="Main"
      data-app-tabbar=""
      className="glass-bar fixed inset-x-0 bottom-0 z-40 border-t pb-[env(safe-area-inset-bottom)] sm:hidden"
    >
      <ul className="flex h-16 items-center justify-around px-2">
        <PrimaryLinks placement="bottom" />
      </ul>
    </nav>
  );
}
