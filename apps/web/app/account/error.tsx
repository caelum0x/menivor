"use client";

import { RouteError } from "@/components/app-shell/RouteError";

export default function AccountError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError error={error} reset={reset} section="your account" />;
}
