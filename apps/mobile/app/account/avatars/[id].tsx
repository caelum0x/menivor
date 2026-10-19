/**
 * Account · Avatar Detail
 *
 * Nav manifest: { route: "/account/avatars/[id]", title: "Avatar" }
 *
 * A single custom (talking-photo) avatar, resolved from GET /api/v1/avatars by
 * its select-id (the value sent as `params.avatar_id` when creating a reel).
 * There is no single-avatar GET, so the screen loads the list and finds the
 * matching preset. Shows the large preview, its metadata (provider / default
 * voice / selector — copyable), a "Create a reel with this avatar" CTA and a
 * lip-sync test that opens the reel composer prefilled. Explicit loading /
 * error / not-found states + pull-to-refresh.
 *
 * Wires endpoint: GET /api/v1/avatars.
 */

import { useCallback, useMemo, useState } from "react";
import {
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { listAvatars } from "@/lib/api";
import {
  avatarLabel,
  avatarSelectId,
  isCustomAvatar,
  type Avatar,
} from "@/lib/types";
import { toDisplayUrl } from "@/src/shared/media";
import { useSession } from "@/src/shared/auth";

import { DetailRows, type DetailRow } from "@/components/account/DetailRows";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { useResource } from "@/components/me/use-resource";

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

export default function AccountAvatarDetailScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const id = firstParam(params.id).trim();

  const fetcher = useCallback(() => listAvatars({ token }), [token]);
  const { status, data, error, reload, setData } =
    useResource<Avatar[]>(fetcher);
  const [refreshing, setRefreshing] = useState(false);

  const avatar = useMemo(
    () => (data ?? []).find((a) => avatarSelectId(a) === id) ?? null,
    [data, id],
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const fresh = await listAvatars({ token });
      setData(() => fresh);
    } catch {
      // keep last-good
    } finally {
      setRefreshing(false);
    }
  }, [token, setData]);

  const rows: DetailRow[] = useMemo(() => {
    if (!avatar) return [];
    const out: DetailRow[] = [];
    out.push({
      label: "Type",
      value: isCustomAvatar(avatar)
        ? "Custom talking photo"
        : "Provider catalog",
    });
    const provider = (avatar.provider || "").trim();
    if (provider) out.push({ label: "Provider", value: provider });
    const voice = (avatar.voice_name || "").trim();
    if (voice) out.push({ label: "Default voice", value: voice, mono: true });
    out.push({
      label: "Selector (avatar_id)",
      value: id,
      copyable: true,
      mono: true,
    });
    return out;
  }, [avatar, id]);

  const thumb = avatar ? toDisplayUrl(avatar.thumbnail_url) : undefined;
  const label = avatar ? avatarLabel(avatar) : "Avatar";

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={reload}
      loadingLabel="Loading avatar…"
    >
      <Stack.Screen options={{ title: avatar ? label : "Avatar" }} />
      {!avatar ? (
        <View style={styles.notFound}>
          <Text style={styles.notFoundTitle}>Avatar not found</Text>
          <Text style={styles.notFoundText}>
            This avatar is no longer in your library. It may have been removed.
          </Text>
          <Pressable
            style={styles.secondary}
            onPress={() => router.back()}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Back to avatars</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => void onRefresh()}
              tintColor={colors.accent}
            />
          }
        >
          <View style={styles.hero}>
            {thumb ? (
              <Image
                source={{ uri: thumb }}
                style={styles.heroImage}
                resizeMode="cover"
                accessibilityLabel={label}
              />
            ) : (
              <Text style={styles.heroEmpty}>
                {label.slice(0, 1).toUpperCase()}
              </Text>
            )}
          </View>

          <Text style={styles.title}>{label}</Text>

          <DetailRows rows={rows} />

          <Pressable
            style={styles.primary}
            onPress={() =>
              router.push({
                pathname: "/(tabs)/create",
                params: { avatar_id: id },
              })
            }
            accessibilityRole="button"
          >
            <Text style={styles.primaryText}>Create a reel with this avatar</Text>
          </Pressable>

          <Pressable
            style={styles.secondary}
            onPress={() =>
              router.push({
                pathname: "/(tabs)/create",
                params: { avatar_id: id, lipsync_test: "1" },
              })
            }
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Run a lip-sync test</Text>
          </Pressable>

          <Text style={styles.hint}>
            The lip-sync test opens the reel composer prefilled with this avatar
            so you can render a short narration clip and see it talk.
          </Text>
        </ScrollView>
      )}
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 48, gap: 16 },
  hero: {
    aspectRatio: 1,
    borderRadius: 20,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  heroImage: { width: "100%", height: "100%" },
  heroEmpty: { color: colors.muted, fontSize: 64, fontWeight: "700" },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  primary: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  primaryText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  hint: { color: colors.muted, fontSize: 12, lineHeight: 18 },
  notFound: {
    flex: 1,
    padding: 24,
    gap: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  notFoundTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  notFoundText: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
  },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 13,
    alignItems: "center",
  },
  secondaryText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
});
