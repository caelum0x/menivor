import type { Metadata } from "next";
import { AdminProviders } from "@/components/admin/AdminProviders";
import { AdminShell } from "@/components/admin/AdminShell";

export const metadata: Metadata = {
  title: "Admin",
  robots: { index: false, follow: false },
};

/**
 * The admin console is authenticated + client-driven (the headless refine router
 * reads `useSearchParams()`), so it is never statically prerendered — rendering
 * happens per-request. This also avoids a CSR-bailout prerender error at build.
 */
export const dynamic = "force-dynamic";

/**
 * Platform-admin console layout. Wraps every `/admin/*` route in the headless
 * refine runtime ({@link AdminProviders}) and the `is_staff`-gated
 * {@link AdminShell}. The console is SEPARATE from workspace RBAC — access is
 * decided by `is_staff` alone, and every underlying endpoint re-enforces it.
 */
export default function AdminLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <AdminProviders>
      <AdminShell>{children}</AdminShell>
    </AdminProviders>
  );
}
