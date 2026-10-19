"use client";

import Link from "next/link";
import { Check, Loader2, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface FollowButtonProps {
  /** Whether a caller is signed in (drives Follow vs. a sign-in prompt). */
  signedIn: boolean;
  /** The caller's current follow state for this creator. */
  following: boolean;
  /** True while a follow/unfollow request is in flight. */
  busy: boolean;
  /** Toggle handler (follow when not following, unfollow otherwise). */
  onToggle: () => void;
  className?: string;
}

/**
 * The Follow / Following toggle on a creator profile. Presentational: the parent
 * page owns the follow state, the request, and error handling. Signed-out
 * visitors get a "Sign in to follow" link instead of a live toggle, so the public
 * profile never attempts an unauthenticated write.
 */
export function FollowButton({
  signedIn,
  following,
  busy,
  onToggle,
  className,
}: Readonly<FollowButtonProps>) {
  if (!signedIn) {
    return (
      <Button asChild variant="outline" className={className}>
        <Link href="/sign-in">
          <UserPlus aria-hidden /> Sign in to follow
        </Link>
      </Button>
    );
  }

  return (
    <Button
      type="button"
      variant={following ? "outline" : "default"}
      onClick={onToggle}
      disabled={busy}
      aria-pressed={following}
      className={className}
    >
      {busy ? (
        <>
          <Loader2 className="animate-spin" aria-hidden /> Saving…
        </>
      ) : following ? (
        <>
          <Check aria-hidden /> Following
        </>
      ) : (
        <>
          <UserPlus aria-hidden /> Follow
        </>
      )}
    </Button>
  );
}
