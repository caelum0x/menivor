"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Ellipsis, SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useIsStaff } from "@/components/admin/use-is-staff";
import {
  APP_NAV_GROUPS,
  NAV_ADVANCED_STORAGE_KEY,
  hiddenNavCount,
  visibleNavGroups,
  type AppNavItem,
} from "./nav-items";

function isActive(pathname: string, item: AppNavItem): boolean {
  return pathname === item.href;
}

function readAdvancedPreference(): boolean | null {
  try {
    const raw = window.localStorage.getItem(NAV_ADVANCED_STORAGE_KEY);
    return raw === null ? null : raw === "1";
  } catch {
    return null;
  }
}

function writeAdvancedPreference(value: boolean): void {
  try {
    window.localStorage.setItem(NAV_ADVANCED_STORAGE_KEY, value ? "1" : "0");
  } catch {
    // Storage blocked: the toggle still works for this page view.
  }
}

/**
 * WP3.2: this menu is shown only to verified staff (or to everyone when
 * `NEXT_PUBLIC_MENIVOR_STAFF_TOOLS=open`); see `PrimaryNav`.
 *
 * Simple vs. all-tools menu. New users get the short menu (create, library,
 * publish, credits, account); the ~40 studio, lab, team and developer tools
 * appear once they opt in. Verified staff default to everything. An explicit
 * choice in this browser always wins. Hidden pages stay reachable by URL.
 */
function useAdvancedNav(): readonly [boolean, (next: boolean) => void] {
  const { status } = useIsStaff();
  const [stored, setStored] = React.useState<boolean | null>(null);

  React.useEffect(() => {
    setStored(readAdvancedPreference());
  }, []);

  const set = React.useCallback((next: boolean) => {
    setStored(next);
    writeAdvancedPreference(next);
  }, []);

  return [stored ?? status === "staff", set] as const;
}

/**
 * "More": every secondary surface, grouped, behind one icon-only button. A
 * dropdown under the top bar on desktop; a sheet above the tab bar on mobile.
 * Closes on route change, Escape and outside click.
 */
export function AppNavMenu({ placement = "top" }: Readonly<{ placement?: "top" | "bottom" }>) {
  const pathname = usePathname() ?? "";
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const panelId = React.useId();
  const [advanced, setAdvanced] = useAdvancedNav();
  const groups = visibleNavGroups(APP_NAV_GROUPS, advanced);
  const hiddenCount = hiddenNavCount(APP_NAV_GROUPS);

  React.useEffect(() => {
    setOpen(false);
  }, [pathname]);

  React.useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-label={open ? "Close more" : "More"}
        aria-expanded={open}
        aria-controls={panelId}
        aria-haspopup="true"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          "group/tip relative flex size-10 items-center justify-center rounded-xl transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          open
            ? "bg-white/[0.08] text-foreground"
            : "text-muted-foreground hover:bg-white/[0.05] hover:text-foreground",
        )}
      >
        {open ? (
          <X className="size-5" aria-hidden />
        ) : (
          <Ellipsis className="size-5" aria-hidden />
        )}
        <span
          role="presentation"
          className={cn(
            "pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-background/95 px-2 py-1 text-xs text-foreground opacity-0 shadow-sm transition-opacity duration-150 group-hover/tip:opacity-100 group-focus-visible/tip:opacity-100",
            placement === "top" ? "top-full mt-2" : "bottom-full mb-2",
            open && "hidden",
          )}
        >
          More
        </span>
      </button>

      {open && (
        <nav
          id={panelId}
          aria-label="App"
          className={cn(
            "z-50 overflow-y-auto glass-strong bg-background/95 p-4",
            placement === "top"
              ? "fixed inset-x-0 top-16 max-h-[calc(100dvh-4rem)] sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[640px] sm:rounded-2xl"
              : "fixed inset-x-0 bottom-16 max-h-[calc(100dvh-8rem)] rounded-t-2xl",
          )}
        >
          <div className="grid gap-5 sm:grid-cols-3">
            {groups.map((group) => (
              <div key={group.label}>
                <p className="mb-1.5 px-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {group.label}
                </p>
                <ul className="space-y-0.5">
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    const active = isActive(pathname, item);
                    return (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          aria-current={active ? "page" : undefined}
                          className={cn(
                            "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                            active
                              ? "bg-secondary text-foreground"
                              : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                          )}
                        >
                          <Icon className="size-4 shrink-0" aria-hidden />
                          {item.label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-4 flex items-center justify-between gap-3 border-t border-border pt-3">
            <p className="text-xs text-muted-foreground">
              {advanced
                ? "Showing every studio, lab, team and developer tool."
                : `${hiddenCount} more tools for power users are hidden.`}
            </p>
            <Button
              variant="ghost"
              size="sm"
              aria-pressed={advanced}
              onClick={() => setAdvanced(!advanced)}
            >
              <SlidersHorizontal className="size-4" aria-hidden />
              {advanced ? "Show fewer tools" : "Show all tools"}
            </Button>
          </div>
        </nav>
      )}
    </div>
  );
}
