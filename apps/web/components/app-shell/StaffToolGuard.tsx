"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { useIsStaff } from "@/components/admin/use-is-staff";
import { isStaffToolRoute, staffToolsGated } from "./nav-items";

/**
 * WP3.2: a non-staff visitor on a staff-only tool page is sent to Home
 * (`/reels`) instead of seeing a 404. Staff keep every tool. The API still
 * enforces its own access rules; this only shapes the web surface.
 * Renders nothing. Mounted once in the root layout.
 */
export function StaffToolGuard() {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const gated = staffToolsGated() && isStaffToolRoute(pathname);
  if (!gated) return null;
  return <RedirectWhenNotStaff router={router} />;
}

function RedirectWhenNotStaff({
  router,
}: Readonly<{ router: ReturnType<typeof useRouter> }>) {
  const { status } = useIsStaff();
  React.useEffect(() => {
    if (status === "denied") router.replace("/reels");
  }, [status, router]);
  return null;
}
