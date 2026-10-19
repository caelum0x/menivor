"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogIn, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { signInHref } from "@/lib/auth-redirect";
import { cn } from "@/lib/utils";
import { friendlyErrorMessage, isSignedOutError } from "./friendly";

export interface LoadErrorProps {
  /** The thrown value. Raw text is never rendered as-is. */
  error: unknown;
  /** Re-run the failed load. Omit to hide the Retry action. */
  onRetry?: () => void;
  /** Sentence used when the error carries nothing a person can use. */
  fallback?: string;
  className?: string;
}

/**
 * A failed load: one calm sentence plus one action. Signed-out failures send
 * the user to sign in (and back here afterwards) instead of offering a retry
 * that would fail the same way.
 */
export function LoadError({ error, onRetry, fallback, className }: LoadErrorProps) {
  const pathname = usePathname() || "/";
  const signedOut = isSignedOutError(error);
  const message = signedOut
    ? "Sign in to see this page."
    : friendlyErrorMessage(error, fallback ?? "We couldn't load this. Please try again.");

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/[0.08] bg-white/[0.03] px-4 py-3",
        className,
      )}
    >
      <p className="text-sm text-foreground/90">{message}</p>
      {signedOut ? (
        <Button asChild size="sm">
          <Link href={signInHref(pathname)}>
            <LogIn className="mr-1.5 h-4 w-4" aria-hidden />
            Sign in
          </Link>
        </Button>
      ) : onRetry ? (
        <Button type="button" size="sm" variant="outline" onClick={onRetry}>
          <RotateCw className="mr-1.5 h-4 w-4" aria-hidden />
          Retry
        </Button>
      ) : null}
    </div>
  );
}
