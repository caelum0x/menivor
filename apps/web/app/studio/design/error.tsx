"use client";

import { RouteError } from "@/components/app-shell/RouteError";

export default function DesignStudioError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError error={error} reset={reset} section="Design Studio" />;
}
