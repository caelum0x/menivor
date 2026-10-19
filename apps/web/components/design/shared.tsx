"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";

import { readableApiError } from "@/src/shared/launch-gate/gate";

/** Readable copy for an API error (no request ids; launch refusals explained). */
export function errorMessage(err: unknown): string {
  return readableApiError(err, "Something went wrong. Try again.");
}

/** Request options with the Clerk token when signed in (device key otherwise). */
export function useRequestOptions(): () => Promise<{ token?: string }> {
  const { getToken } = useAuth();
  return React.useCallback(async () => {
    try {
      const token = (await getToken()) ?? undefined;
      return token ? { token } : {};
    } catch {
      return {};
    }
  }, [getToken]);
}

export function ErrorText({ message }: { message: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

export function blankCanvas(background = "#ffffff") {
  return { version: 1 as const, pages: [{ background, layers: [] }] };
}

export function fitScale(width: number, height: number, maxW: number, maxH: number): number {
  return Math.min(maxW / width, maxH / height);
}

export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
