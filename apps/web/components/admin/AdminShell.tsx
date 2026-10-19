"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Loader2, ShieldAlert, ShieldCheck } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useIsStaff } from "@/components/admin/use-is-staff";
import { MenivorMark } from "@/components/brand/MenivorMark";

const TABS = [
  { href: "/admin/users", label: "Users" },
  { href: "/admin/workspaces", label: "Workspaces" },
  { href: "/admin/jobs", label: "Jobs" },
  { href: "/admin/compliance", label: "Compliance" },
] as const;

/**
 * Chrome for the platform-admin console: a top bar, resource tabs, and the
 * `is_staff` gate. The console content renders ONLY when the caller is verified
 * as a platform admin; a non-staff caller (incl. a workspace owner) sees a clear
 * "administrators only" state instead of any cross-tenant data.
 */
export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { status, errorMessage } = useIsStaff();

  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <div className="flex items-center gap-2 font-semibold">
            <Link href="/reels" className="flex items-center gap-2">
              <MenivorMark variant="gradient" className="size-7" title="Menivor" />
            </Link>
            <span className="flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              <ShieldCheck className="size-3.5" aria-hidden />
              Admin
            </span>
          </div>
          <UserButton />
        </div>
        {status === "staff" && (
          <nav className="container flex gap-1 pb-2" aria-label="Admin">
            {TABS.map((tab) => {
              const isActive = pathname === tab.href;
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
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
        )}
      </header>

      <section className="container py-10">
        {status === "checking" && (
          <div className="flex items-center justify-center gap-2 py-24 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" aria-hidden />
            Verifying admin access…
          </div>
        )}

        {(status === "denied" || status === "error") && (
          <div className="mx-auto max-w-lg">
            <Card>
              <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
                <span className="flex size-12 items-center justify-center rounded-full bg-destructive/10">
                  <ShieldAlert className="size-6 text-destructive" aria-hidden />
                </span>
                <p className="text-lg font-semibold">
                  {status === "denied"
                    ? "Platform administrators only"
                    : "Couldn't verify admin access"}
                </p>
                <p className="text-sm text-muted-foreground">
                  {status === "denied"
                    ? "This area is restricted to Menivor staff. Workspace roles do not grant platform-admin access."
                    : errorMessage}
                </p>
                <Button asChild variant="outline" size="sm" className="mt-2">
                  <Link href="/reels">Back to reels</Link>
                </Button>
              </CardContent>
            </Card>
          </div>
        )}

        {status === "staff" && (
          <div className="mx-auto max-w-5xl">{children}</div>
        )}
      </section>
    </main>
  );
}
