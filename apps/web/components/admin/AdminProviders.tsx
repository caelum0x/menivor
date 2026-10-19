"use client";

import * as React from "react";
import { Refine } from "@refinedev/core";
import routerProvider from "@refinedev/nextjs-router";
import { createAdminDataProvider } from "@/lib/refine/data-provider";
import { createAdminAccessControl } from "@/lib/refine/access-control";
import { useApiToken } from "@/lib/use-api-token";

/**
 * Mounts the headless refine (`@refinedev/core`, MIT) runtime for the
 * platform-admin console — a REST-style {@link createAdminDataProvider} pointed
 * at the FastAPI `/api/v1` admin endpoints and an {@link createAdminAccessControl}
 * gate backed by the `is_staff` probe. No refine UI kit is used: resources are
 * rendered with the app's own `components/ui/*`. Providers are memoised on the
 * (stable) Clerk token getter so the refine runtime stays mounted across renders.
 */
export function AdminProviders({ children }: { children: React.ReactNode }) {
  const getApiToken = useApiToken();

  const dataProvider = React.useMemo(
    () => createAdminDataProvider(getApiToken),
    [getApiToken],
  );
  const accessControlProvider = React.useMemo(
    () => createAdminAccessControl(getApiToken),
    [getApiToken],
  );

  return (
    <Refine
      dataProvider={dataProvider}
      routerProvider={routerProvider}
      accessControlProvider={accessControlProvider}
      resources={[
        { name: "users", list: "/admin/users", meta: { label: "Users" } },
        {
          name: "workspaces",
          list: "/admin/workspaces",
          meta: { label: "Workspaces" },
        },
        { name: "jobs", list: "/admin/jobs", meta: { label: "Jobs" } },
      ]}
      options={{
        syncWithLocation: false,
        warnWhenUnsavedChanges: false,
        disableTelemetry: true,
      }}
    >
      {children}
    </Refine>
  );
}
