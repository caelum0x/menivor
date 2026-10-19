import type { ReactNode } from "react";
import { Copy, FileVideo, Star, UserRound, Users } from "lucide-react";
import type { CreatorProfile } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { CreatorAvatar } from "@/components/creators/CreatorAvatar";
import { CreatorStat } from "@/components/creators/CreatorStat";
import {
  displayName,
  formatCount,
  formatRating,
  handleLabel,
} from "@/components/creators/format";

export interface CreatorProfileCardProps {
  /** The SAFE public profile to render. */
  profile: Readonly<CreatorProfile>;
  /**
   * The live follower count, lifted so it updates immediately on follow/unfollow.
   * Falls back to `profile.follower_count` at the call site.
   */
  followerCount: number;
  /** The Follow control (or a sign-in prompt) rendered in the header. */
  followSlot?: ReactNode;
}

/**
 * The creator profile header: initials avatar, display name + handle, bio, and a
 * grid of PUBLIC reputation aggregates. Renders ONLY safe fields — the profile
 * shape carries no email, credits, cost/revenue, or user id.
 */
export function CreatorProfileCard({
  profile,
  followerCount,
  followSlot,
}: Readonly<CreatorProfileCardProps>) {
  const name = displayName(profile.display_name, profile.handle);
  const handle = handleLabel(profile.handle);

  return (
    <Card>
      <CardContent className="space-y-6 p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-4">
            <CreatorAvatar
              name={profile.display_name}
              handle={profile.handle}
              className="size-16 text-xl"
            />
            <div className="min-w-0 space-y-1">
              <h1 className="truncate text-2xl font-bold tracking-tight">
                {name}
              </h1>
              {handle && (
                <p className="truncate text-sm text-muted-foreground">
                  {handle}
                </p>
              )}
              {profile.bio && (
                <p className="max-w-prose whitespace-pre-line text-sm text-muted-foreground">
                  {profile.bio}
                </p>
              )}
            </div>
          </div>
          {followSlot && <div className="shrink-0">{followSlot}</div>}
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <CreatorStat
            label="Followers"
            value={formatCount(followerCount)}
            icon={Users}
          />
          <CreatorStat
            label="Following"
            value={formatCount(profile.following_count)}
            icon={UserRound}
          />
          <CreatorStat
            label="Published"
            value={formatCount(profile.published_template_count)}
            icon={FileVideo}
          />
          <CreatorStat
            label="Clones"
            value={formatCount(profile.total_clones_received)}
            icon={Copy}
          />
          <CreatorStat
            label="Avg rating"
            value={formatRating(profile.avg_rating)}
            icon={Star}
          />
        </div>
      </CardContent>
    </Card>
  );
}
