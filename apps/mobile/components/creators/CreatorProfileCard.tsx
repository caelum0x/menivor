/**
 * The public identity card for a creator profile screen: display name, "@handle",
 * bio, and a grid of PUBLIC reputation aggregates. It renders ONLY safe public
 * fields from {@link CreatorProfile} — never credits, email, cost/revenue or a
 * `user_id`. The parent owns the follow control and passes it as `footer` so the
 * card stays purely presentational.
 */

import type { ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";

import type { CreatorProfile } from "@/lib/types";
import { colors } from "@/components/me/theme";

import { CreatorStat } from "./CreatorStat";
import { creatorSubtitle, creatorTitle, formatCompact, formatRating } from "./format";

interface CreatorProfileCardProps {
  profile: CreatorProfile;
  /**
   * Optimistic follower count after a follow/unfollow toggle; falls back to the
   * profile's own `follower_count` when not supplied.
   */
  followerCount?: number;
  /** Optional action area (e.g. the follow button) rendered below the stats. */
  footer?: ReactNode;
}

export function CreatorProfileCard({
  profile,
  followerCount,
  footer,
}: CreatorProfileCardProps) {
  const subtitle = creatorSubtitle(profile);
  const followers =
    typeof followerCount === "number" ? followerCount : profile.follower_count;

  return (
    <View style={styles.card}>
      <Text style={styles.title}>{creatorTitle(profile)}</Text>
      {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}

      {profile.bio ? <Text style={styles.bio}>{profile.bio}</Text> : null}

      <View style={styles.stats}>
        <CreatorStat label="Followers" value={formatCompact(followers)} />
        <CreatorStat
          label="Following"
          value={formatCompact(profile.following_count)}
        />
        <CreatorStat
          label="Published"
          value={formatCompact(profile.published_template_count)}
        />
        <CreatorStat
          label="Clones"
          value={formatCompact(profile.total_clones_received)}
        />
        <CreatorStat label="Rating" value={formatRating(profile.avg_rating)} />
      </View>

      {footer ? <View style={styles.footer}>{footer}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 10,
  },
  title: { color: colors.textPrimary, fontSize: 20, fontWeight: "800" },
  subtitle: { color: colors.accent, fontSize: 14, fontWeight: "600" },
  bio: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  stats: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 4,
  },
  footer: { marginTop: 6 },
});
