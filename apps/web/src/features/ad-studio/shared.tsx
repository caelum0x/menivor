"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";

import { friendlyErrorMessage } from "@/src/shared/errors";
import { cn } from "@/lib/utils";

export { LoadError } from "@/src/shared/errors";

/** Short human sentence for a failed action; never raw API text. */
export function errorMessage(err: unknown): string {
  return friendlyErrorMessage(err);
}

/** Resolve request options with the Clerk token when signed in. */
export function useRequestOptions(): () => Promise<{ token?: string }> {
  const { getToken } = useAuth();
  return React.useCallback(async () => {
    const token = (await getToken()) ?? undefined;
    return token ? { token } : {};
  }, [getToken]);
}

export function ChipToggle({
  selected,
  onToggle,
  children,
  disabled,
  title,
}: {
  selected: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      title={title}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "rounded-full border px-3 py-1.5 text-sm transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        selected
          ? "border-primary bg-primary/15 text-primary"
          : "border-border text-muted-foreground hover:bg-secondary/60",
      )}
    >
      {children}
    </button>
  );
}

export function ErrorText({ message }: { message: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

export function toggleIn<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}
