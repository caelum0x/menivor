"use client";

import type { ComponentProps, ReactNode } from "react";
import Link from "next/link";
import {
  SignIn as ClerkSignIn,
  SignUp as ClerkSignUp,
  SignedIn as ClerkSignedIn,
  SignedOut as ClerkSignedOut,
  UserButton as ClerkUserButton,
  useAuth as useClerkAuth,
  useClerk as useClerkInstance,
} from "@clerk/nextjs";
import { hasRealClerkKey } from "@/lib/clerk";

/**
 * Clerk components and hooks that degrade gracefully when no real Clerk
 * instance is configured (see `lib/clerk.ts`). Without a real key the root
 * layout never mounts `<ClerkProvider>`, and every raw `@clerk/nextjs` hook or
 * control component throws ("can only be used within <ClerkProvider />").
 *
 * The whole app imports Clerk ONLY through this module; an ESLint
 * `no-restricted-imports` rule and `clerk-safe-imports.test.ts` enforce that.
 *
 * `hasRealClerkKey` is a build-time constant, so the conditional hook calls
 * below take the same branch on every render (rules of hooks hold).
 */

interface WithChildren {
  readonly children: ReactNode;
}

export function SignedIn({ children }: WithChildren) {
  if (!hasRealClerkKey) return null;
  return <ClerkSignedIn>{children}</ClerkSignedIn>;
}

export function SignedOut({ children }: WithChildren) {
  // Logged-out is the correct default when Clerk isn't configured.
  if (!hasRealClerkKey) return <>{children}</>;
  return <ClerkSignedOut>{children}</ClerkSignedOut>;
}

export function UserButton(props: ComponentProps<typeof ClerkUserButton>) {
  if (!hasRealClerkKey) return null;
  return <ClerkUserButton {...props} />;
}

function AccountsDisabledNotice({ action }: { readonly action: string }) {
  return (
    <div className="max-w-sm rounded-lg border p-6 text-center">
      <h1 className="text-lg font-semibold">Accounts are not enabled here</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {action} is not configured on this deployment, so reels cannot be
        made here. Use menivor.com to create an account.
      </p>
      <Link
        href="/"
        className="mt-4 inline-block text-sm underline underline-offset-4"
      >
        Back to the home page
      </Link>
    </div>
  );
}

export function SignIn(props: ComponentProps<typeof ClerkSignIn>) {
  if (!hasRealClerkKey) return <AccountsDisabledNotice action="Sign-in" />;
  return <ClerkSignIn {...props} />;
}

export function SignUp(props: ComponentProps<typeof ClerkSignUp>) {
  if (!hasRealClerkKey) return <AccountsDisabledNotice action="Sign-up" />;
  return <ClerkSignUp {...props} />;
}

type ClerkAuth = ReturnType<typeof useClerkAuth>;

async function noToken(): Promise<null> {
  return null;
}

/**
 * Signed-out auth state used when Clerk is not configured. Module-level so the
 * `getToken` reference is stable and effects keyed on it do not loop. A `null`
 * token makes the shared API transport fall back to the device session.
 */
const SIGNED_OUT_AUTH = {
  isLoaded: true,
  isSignedIn: false,
  userId: null,
  sessionId: null,
  sessionClaims: null,
  actor: null,
  orgId: null,
  orgRole: null,
  orgSlug: null,
  has: () => false,
  signOut: async () => undefined,
  getToken: noToken,
} as unknown as ClerkAuth;

export function useAuth(
  ...args: Parameters<typeof useClerkAuth>
): ClerkAuth {
  if (!hasRealClerkKey) return SIGNED_OUT_AUTH;
  // eslint-disable-next-line react-hooks/rules-of-hooks -- build-time constant branch
  return useClerkAuth(...args);
}

type ClerkInstance = ReturnType<typeof useClerkInstance>;

/** Only `signOut` is meaningful without Clerk: there is no session to end. */
const NO_CLERK = {
  loaded: false,
  signOut: async () => undefined,
} as unknown as ClerkInstance;

export function useClerk(): ClerkInstance {
  if (!hasRealClerkKey) return NO_CLERK;
  // eslint-disable-next-line react-hooks/rules-of-hooks -- build-time constant branch
  return useClerkInstance();
}
