"use client";

import { useAuth } from "@/components/auth/clerk-safe";
import { hasRealClerkKey } from "@/lib/clerk";

export interface SignedInState {
  /** True once Clerk has resolved (always true when Clerk is not configured). */
  readonly isLoaded: boolean;
  /** True only for a real, signed-in Clerk session. */
  readonly isSignedIn: boolean;
}

function useClerkSignedInState(): SignedInState {
  const { isLoaded, isSignedIn } = useAuth();
  return { isLoaded, isSignedIn: Boolean(isSignedIn) };
}

const SIGNED_OUT: SignedInState = { isLoaded: true, isSignedIn: false };

function useNoClerkSignedInState(): SignedInState {
  return SIGNED_OUT;
}

/**
 * Whether the visitor holds a real account session. `hasRealClerkKey` is a
 * build-time constant, so the chosen implementation never changes between
 * renders (hook order stays stable). Without a Clerk instance every visitor is
 * a device-session guest.
 */
export const useSignedInState: () => SignedInState = hasRealClerkKey
  ? useClerkSignedInState
  : useNoClerkSignedInState;
