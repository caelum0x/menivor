"use client";

import { RouteError } from "@/components/app-shell/RouteError";

/**
 * Root error boundary: any segment without its own `error.tsx` falls back to
 * this recoverable screen instead of a blank page.
 */
export default function RootRouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError error={error} reset={reset} />;
}
