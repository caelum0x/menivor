"use client";

import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useIsStaff } from "@/components/admin/use-is-staff";

/**
 * Dashboard nav entry for the platform-admin console. Renders ONLY when the
 * caller is verified as `is_staff` (probed via {@link useIsStaff}), so a normal
 * user — including a workspace owner — never sees the Admin link. The `/admin`
 * routes are independently hard-gated server-side regardless.
 */
export function AdminNavLink() {
  const { status } = useIsStaff();
  if (status !== "staff") return null;

  return (
    <Button asChild variant="ghost" size="sm">
      <Link href="/admin/users">
        <ShieldCheck className="size-4" aria-hidden /> Admin
      </Link>
    </Button>
  );
}
