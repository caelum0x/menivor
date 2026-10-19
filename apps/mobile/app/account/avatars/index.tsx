/**
 * Account · Custom Avatars
 *
 * Nav manifest:
 *   { route: "/account/avatars",      title: "Custom Avatars" }
 *   { route: "/account/avatars/[id]", title: "Avatar" }
 *
 * The caller's own photo→avatar library (GET /api/v1/avatars, filtered to
 * `source === "preset"`). Create a new talking-photo avatar from a selfie
 * (POST /api/v1/avatars) via the shared CreateAvatarForm with an optimistic
 * prepend, pull-to-refresh, and tap any avatar to drill into its detail (large
 * preview + selector + lip-sync test). Explicit loading / error / empty states.
 *
 * Wires endpoint: GET/POST /api/v1/avatars.
 */

import { useCallback, useState } from "react";
import {
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import { listAvatars } from "@/lib/api";
import {
  avatarLabel,
  avatarSelectId,
  isCustomAvatar,
  type Avatar,
  type CreateAvatarResult,
} from "@/lib/types";
import { toDisplayUrl } from "@/src/shared/media";
import { useSession } from "@/src/shared/auth";

import { CreateAvatarForm } from "@/components/avatars/CreateAvatarForm";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { Icon } from "@/components/ui/Icon";

export default function AccountAvatarsScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const fetcher = useCallback(() => listAvatars({ token }), [token]);
  const { status, data, error, reload, setData } =
    useResource<Avatar[]>(fetcher);
  const [refreshing, setRefreshing] = useState(false);

  const customAvatars = (data ?? []).filter(isCustomAvatar);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const fresh = await listAvatars({ token });
      setData(() => fresh);
    } catch {
      // Surface nothing on a pull-to-refresh miss; the last-good list stays.
    } finally {
      setRefreshing(false);
    }
  }, [token, setData]);

  const onCreated = useCallback(
    (created: CreateAvatarResult) => {
      const avatar: Avatar = { source: "preset", ...created };
      setData((prev) => [avatar, ...(prev ?? [])]);
    },
    [setData],
  );

  const openDetail = useCallback(
    (avatar: Avatar) => {
      const id = avatarSelectId(avatar);
      if (!id) return;
      router.push({ pathname: "/account/avatars/[id]", params: { id } });
    },
    [router],
  );

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => void onRefresh()}
          tintColor={colors.accent}
        />
      }
    >
      <Text style={styles.intro}>
        Turn a selfie into your own talking-photo avatar that lip-syncs each
        reel’s narration. Tap any avatar to preview it, copy its selector, or run
        a lip-sync test.
      </Text>

      <Section title="NEW AVATAR">
        <CreateAvatarForm token={token} onCreated={onCreated} />
      </Section>

      <Section title="YOUR AVATARS">
        <SectionState status={status} error={error} onRetry={reload}>
          {customAvatars.length === 0 ? (
            <Text style={styles.empty}>
              No custom avatars yet. Upload a selfie above to create a
              talking-photo avatar you can reuse on every reel.
            </Text>
          ) : (
            <View style={styles.list}>
              {customAvatars.map((avatar, index) => {
                const thumb = toDisplayUrl(avatar.thumbnail_url);
                const label = avatarLabel(avatar);
                const selectId = avatarSelectId(avatar);
                return (
                  <Pressable
                    key={avatar.id ?? avatar.provider_avatar_id ?? index}
                    style={styles.card}
                    onPress={() => openDetail(avatar)}
                    accessibilityRole="button"
                    accessibilityLabel={`Open ${label}`}
                  >
                    <View style={styles.thumbBox}>
                      {thumb ? (
                        <Image
                          source={{ uri: thumb }}
                          style={styles.thumb}
                          resizeMode="cover"
                        />
                      ) : (
                        <Text style={styles.thumbEmpty}>
                          {label.slice(0, 1).toUpperCase()}
                        </Text>
                      )}
                    </View>
                    <View style={styles.body}>
                      <Text style={styles.name} numberOfLines={1}>
                        {label}
                      </Text>
                      <Text style={styles.selector} numberOfLines={1}>
                        {selectId}
                      </Text>
                    </View>
                    <Icon name="chevron-forward" style={styles.chevron} />
                  </Pressable>
                );
              })}
            </View>
          )}
        </SectionState>
      </Section>

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 20 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 20,
  },
  list: { gap: 10 },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
  },
  thumbBox: {
    width: 44,
    height: 44,
    borderRadius: 10,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  thumb: { width: 44, height: 44 },
  thumbEmpty: { color: colors.muted, fontSize: 18, fontWeight: "700" },
  body: { flex: 1, gap: 4 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  selector: { color: colors.muted, fontSize: 12 },
  chevron: { color: colors.muted, fontSize: 24, fontWeight: "300", paddingHorizontal: 4 },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
  spacer: { height: 40 },
});
