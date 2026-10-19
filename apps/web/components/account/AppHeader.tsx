"use client";

import { AppTopBar } from "@/components/app-shell/AppTopBar";

/**
 * Top bar for the Account / Connections / Workspace surfaces. Delegates to the
 * shared {@link AppTopBar} so every app page has the same navigation.
 */
export function AppHeader() {
  return <AppTopBar />;
}
