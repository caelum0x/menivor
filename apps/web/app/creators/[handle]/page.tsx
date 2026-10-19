"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { useAuth } from "@/components/auth/clerk-safe";
import { AlertCircle, UserRound } from "lucide-react";
import {
  ApiError,
  followCreator,
  getCreatorProfile,
  listFollowing,
  unfollowCreator,
} from "@/lib/api";
import type { CreatorProfile } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CreatorsHeader } from "@/components/creators/CreatorsHeader";
import { CreatorProfileCard } from "@/components/creators/CreatorProfileCard";
import { FollowButton } from "@/components/creators/FollowButton";
import { EmptyPanel, ErrorPanel } from "@/components/creators/StatePanels";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { ChannelLink } from "@/src/features/ott-player/ChannelLink";

type LoadState = "loading" | "ready" | "error";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/** Read the `[handle]` dynamic segment (may be a handle OR a user id). */
function useHandleParam(): string {
  const params = useParams<{ handle: string }>();
  const raw = params?.handle;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return typeof value === "string" ? decodeURIComponent(value) : "";
}

export default function CreatorProfilePage() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  // The route param addresses the profile (getCreatorProfile accepts a handle OR
  // an id) AND is the follow target. Following requires the creator's user id, so
  // the leaderboard links here by `user_id`; a handle-addressed visit can still
  // view the profile but a follow attempt may not resolve (surfaced as an error).
  const creatorRef = useHandleParam();

  const [status, setStatus] = React.useState<LoadState>("loading");
  const [profile, setProfile] = React.useState<CreatorProfile | null>(null);
  const [loadError, setLoadError] = React.useState<string>("");

  const [followerCount, setFollowerCount] = React.useState(0);
  const [following, setFollowing] = React.useState(false);
  const [followBusy, setFollowBusy] = React.useState(false);
  const [followError, setFollowError] = React.useState<string>("");
  const [notFound, setNotFound] = React.useState(false);

  const load = React.useCallback(async () => {
    if (!creatorRef) {
      setStatus("error");
      setLoadError("No creator was specified.");
      return;
    }
    setStatus("loading");
    setLoadError("");
    setNotFound(false);
    try {
      const token = (await getToken()) ?? undefined;
      const result = await getCreatorProfile(creatorRef, { token });
      setProfile(result);
      setFollowerCount(result.follower_count);

      // Seed the follow toggle: match the fetched handle against the caller's
      // follow list (the SAFE list exposes handles, never user ids). Best-effort —
      // a failure here never blocks rendering the public profile.
      if (isSignedIn && result.handle) {
        try {
          const followees = await listFollowing({ token });
          const handleLower = result.handle.toLowerCase();
          setFollowing(
            followees.some(
              (p) => p.handle && p.handle.toLowerCase() === handleLower,
            ),
          );
        } catch {
          setFollowing(false);
        }
      } else {
        setFollowing(false);
      }

      setStatus("ready");
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
        setStatus("ready");
        return;
      }
      setLoadError(errorMessage(err, "Something went wrong loading this creator."));
      setStatus("error");
    }
  }, [creatorRef, getToken, isSignedIn]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  const handleToggle = React.useCallback(async () => {
    setFollowBusy(true);
    setFollowError("");
    try {
      const token = (await getToken()) ?? undefined;
      const result = following
        ? await unfollowCreator(creatorRef, { token })
        : await followCreator(creatorRef, { token });
      setFollowing(result.following);
      setFollowerCount(result.follower_count);
    } catch (err) {
      setFollowError(errorMessage(err, "Couldn't update your follow."));
    } finally {
      setFollowBusy(false);
    }
  }, [creatorRef, following, getToken]);

  return (
    <main className="min-h-dvh">
      <CreatorsHeader />

      <section className="container max-w-3xl py-8">
        {status === "loading" && <ProfileSkeleton />}

        {status === "error" && (
          <ErrorPanel
            title="Couldn't load this creator"
            message={loadError}
            onRetry={() => void load()}
          />
        )}

        {status === "ready" && notFound && (
          <EmptyPanel
            icon={<UserRound className="size-6 text-primary" aria-hidden />}
            title="Creator not found"
            description="This creator profile doesn't exist or is no longer available."
          />
        )}

        {status === "ready" && !notFound && profile && (
          <div className="space-y-4">
            <CreatorProfileCard
              profile={profile}
              followerCount={followerCount}
              followSlot={
                <FollowButton
                  signedIn={Boolean(isSignedIn)}
                  following={following}
                  busy={followBusy}
                  onToggle={() => void handleToggle()}
                />
              }
            />
            {profile.handle && <ChannelLink handle={profile.handle} />}
            {followError && (
              <p
                role="alert"
                className="flex items-center gap-1.5 text-sm text-destructive"
              >
                <AlertCircle className="size-4 shrink-0" aria-hidden />
                {followError}
              </p>
            )}
          </div>
        )}
      </section>
    </main>
  );
}

function ProfileSkeleton() {
  return (
    <Card>
      <CardContent className="space-y-6 p-6">
        <div className="flex items-start gap-4">
          <Skeleton className="size-16 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-7 w-48" />
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-4 w-full max-w-md" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[68px] rounded-lg" />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
