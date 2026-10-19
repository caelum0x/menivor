/**
 * Public Creator Profile screen.
 *
 * Shows a creator's SAFE public identity (display name, "@handle", bio) and their
 * PUBLIC reputation aggregates. The `[id]` route param is a handle OR a user id —
 * both are accepted by GET /creators/{handle_or_id} (PUBLIC, no auth). The profile
 * NEVER carries credits, email, cost/revenue or a `user_id`, so nothing private is
 * surfaced.
 *
 * A signed-in visitor can follow / unfollow the creator (owner-scoped, auth). The
 * follow button is hidden when viewing your own profile or when signed out. The
 * initial follow-state is best-effort seeded from GET /me/following (matched by
 * handle); a toggle then reflects the authoritative server result. The follow
 * endpoints address the creator by the same route param — deep-links from the
 * leaderboard / "My creator profile" pass a real user id, so follow resolves; a
 * handle-only link that can't be followed degrades to an inline error.
 */

import { useCallback, useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View, Pressable, ActivityIndicator } from "react-native";

import { Stack, useLocalSearchParams } from "expo-router";

import {
  followCreator,
  getCreatorProfile,
  isAbortError,
  listFollowing,
  me as fetchMe,
  unfollowCreator,
} from "@/lib/api";
import { useSession } from "@/src/shared/auth";
import type { CreatorProfile } from "@/lib/types";

import { SectionState } from "@/components/me/Section";
import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { CreatorProfileCard } from "@/components/creators/CreatorProfileCard";
import { creatorTitle } from "@/components/creators/format";

export default function CreatorScreen() {
  const params = useLocalSearchParams<{ id: string }>();
  const handleOrId = typeof params.id === "string" ? params.id : "";
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const fetcher = useCallback(
    () => getCreatorProfile(handleOrId, { token }),
    [handleOrId, token],
  );
  const profile = useResource<CreatorProfile>(fetcher);

  // The caller's own id — used to hide the follow control on your own profile
  // (the common deep-links pass a user id, so an id === id match detects self).
  const [myUserId, setMyUserId] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setMyUserId(null);
      return;
    }
    const controller = new AbortController();
    fetchMe({ token, signal: controller.signal })
      .then((profileMe) => setMyUserId(profileMe.user_id || null))
      .catch((err: unknown) => {
        if (!isAbortError(err)) setMyUserId(null);
      });
    return () => controller.abort();
  }, [token]);

  // Follow state (best-effort initial seed from /me/following, then authoritative
  // after a toggle). `null` means "unknown / not yet resolved".
  const [following, setFollowing] = useState<boolean | null>(null);
  const [followerCount, setFollowerCount] = useState<number | null>(null);
  const [followBusy, setFollowBusy] = useState(false);
  const [followError, setFollowError] = useState<string | null>(null);

  const loadedProfile = profile.data;
  const isSelf = myUserId != null && myUserId === handleOrId;

  useEffect(() => {
    // Only seed when signed in, not self, and the profile has loaded with a
    // handle we can match against the following list.
    if (!token || isSelf || !loadedProfile) return;
    const targetHandle = (loadedProfile.handle || "").trim().toLowerCase();
    if (!targetHandle) {
      setFollowing(false);
      return;
    }
    const controller = new AbortController();
    listFollowing({ token, signal: controller.signal })
      .then((list) => {
        setFollowing(
          list.some((f) => (f.handle || "").trim().toLowerCase() === targetHandle),
        );
      })
      .catch((err: unknown) => {
        if (!isAbortError(err)) setFollowing(false);
      });
    return () => controller.abort();
  }, [token, isSelf, loadedProfile]);

  const onToggleFollow = useCallback(async () => {
    if (!token || followBusy) return;
    setFollowBusy(true);
    setFollowError(null);
    try {
      const result = following
        ? await unfollowCreator(handleOrId, { token })
        : await followCreator(handleOrId, { token });
      setFollowing(result.following);
      setFollowerCount(result.follower_count);
    } catch (err) {
      setFollowError(describeError(err, "Couldn't update follow. Try again."));
    } finally {
      setFollowBusy(false);
    }
  }, [token, followBusy, following, handleOrId]);

  const showFollow = !!token && !isSelf;
  const title = loadedProfile ? creatorTitle(loadedProfile) : "Creator";

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
    >
      <Stack.Screen options={{ title }} />

      <SectionState
        status={profile.status}
        error={profile.error}
        onRetry={profile.reload}
        loadingLabel="Loading profile…"
      >
        {loadedProfile ? (
          <CreatorProfileCard
            profile={loadedProfile}
            followerCount={followerCount ?? undefined}
            footer={
              showFollow ? (
                <>
                  <Pressable
                    style={[
                      styles.follow,
                      following ? styles.following : styles.notFollowing,
                      followBusy && styles.disabled,
                    ]}
                    onPress={() => void onToggleFollow()}
                    disabled={followBusy}
                    accessibilityRole="button"
                    accessibilityLabel={following ? "Unfollow creator" : "Follow creator"}
                    accessibilityState={{ disabled: followBusy, selected: !!following }}
                  >
                    {followBusy ? (
                      <ActivityIndicator
                        color={following ? colors.textSecondary : colors.textPrimary}
                      />
                    ) : (
                      <Text
                        style={[
                          styles.followText,
                          following && styles.followingText,
                        ]}
                      >
                        {following ? "Following" : "Follow"}
                      </Text>
                    )}
                  </Pressable>
                  {followError ? (
                    <Text style={styles.error}>{followError}</Text>
                  ) : null}
                </>
              ) : null
            }
          />
        ) : null}
      </SectionState>

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24 },
  follow: {
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  notFollowing: { backgroundColor: colors.primary },
  following: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
  },
  disabled: { opacity: 0.6 },
  followText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
  followingText: { color: colors.textSecondary },
  error: { color: colors.error, fontSize: 14, marginTop: 8 },
  spacer: { height: 40 },
});
