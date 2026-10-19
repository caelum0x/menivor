"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SignedIn, SignedOut, UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { signInHref, signUpHref } from "@/lib/auth-redirect";

/**
 * Right-hand auth control for app headers: the Clerk user menu when signed
 * in; "Sign in" + "Save my work" (sign-up) for device-session guests, both
 * returning to the current page afterwards.
 */
export function AuthControls() {
  const pathname = usePathname() || "/reels";
  return (
    <>
      <SignedIn>
        <UserButton afterSignOutUrl="/" />
      </SignedIn>
      <SignedOut>
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex">
            <Link href={signInHref(pathname)}>Sign in</Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link href={signUpHref(pathname)}>Sign up</Link>
          </Button>
        </div>
      </SignedOut>
    </>
  );
}
