/**
 * Studio · Avatar Gallery
 *
 * Nav manifest:
 *   { route: "/studio/avatars",     title: "Avatar Gallery" }
 *   { route: "/studio/avatar/[id]", title: "Avatar" }
 *
 * The full avatar catalog (GET /avatars): provider (catalog) avatars plus the
 * caller's own custom photo→avatar presets, in a two-column thumbnail grid.
 * Search by name, filter by source (all / custom / catalog), pull-to-refresh,
 * and tap a tile for its detail. A header CTA deep-links to the create-a-custom
 * -avatar flow (/avatars). Explicit loading / error / empty states.
 */

import { useCallback, useMemo, useState } from "react";
import {
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import { listAvatars } from "@/lib/api";
import {
  avatarLabel,
  avatarSelectId,
  isCustomAvatar,
  type Avatar,
} from "@/lib/types";
import { toDisplayUrl } from "@/src/shared/media";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { FilterChips } from "@/components/studio/FilterChips";

type SourceFilter = "all" | "custom" | "catalog";

const FILTERS: { id: SourceFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "custom", label: "My avatars" },
  { id: "catalog", label: "Catalog" },
];

export default function StudioAvatarsScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const [avatars, setAvatars] = useState<Avatar[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState<SourceFilter>("all");

  const load = useCallback(
    async (mode: "initial" | "refresh") => {
      if (mode === "initial") setStatus("loading");
      else setRefreshing(true);
      try {
        const data = await listAvatars({ token });
        setAvatars(data);
        setStatus("ready");
        setError("");
      } catch (err) {
        setError(describeError(err, "Failed to load avatars."));
        if (mode === "initial") setStatus("error");
      } finally {
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return avatars.filter((a) => {
      const custom = isCustomAvatar(a);
      if (source === "custom" && !custom) return false;
      if (source === "catalog" && custom) return false;
      if (!q) return true;
      return avatarLabel(a).toLowerCase().includes(q);
    });
  }, [avatars, search, source]);

  const keyExtractor = useCallback(
    (a: Avatar, index: number) =>
      a.id ?? a.avatar_id ?? a.provider_avatar_id ?? String(index),
    [],
  );

  const renderItem = useCallback(
    ({ item }: { item: Avatar }) => {
      const thumb = toDisplayUrl(item.thumbnail_url);
      const label = avatarLabel(item);
      const custom = isCustomAvatar(item);
      const id = avatarSelectId(item);
      return (
        <Pressable
          style={styles.tile}
          onPress={() =>
            router.push({
              pathname: "/studio/avatar/[id]",
              params: { id },
            })
          }
          disabled={!id}
          accessibilityRole="button"
          accessibilityLabel={label}
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
            <View style={[styles.badge, custom && styles.badgeCustom]}>
              <Text style={styles.badgeText}>
                {custom ? "Custom" : "Catalog"}
              </Text>
            </View>
          </View>
          <Text style={styles.name} numberOfLines={1}>
            {label}
          </Text>
        </Pressable>
      );
    },
    [router],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        Every avatar you can drive a reel with — the provider catalog plus your
        own talking-photo avatars.
      </Text>
      <Pressable
        style={styles.cta}
        onPress={() => router.push("/account/avatars")}
        accessibilityRole="button"
      >
        <Text style={styles.ctaText}>Create a custom avatar from a photo</Text>
      </Pressable>
      <TextInput
        style={styles.search}
        value={search}
        onChangeText={setSearch}
        placeholder="Search avatars"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
      />
      <FilterChips options={FILTERS} selected={source} onSelect={(id) => setSource(id as SourceFilter)} />
      <Text style={styles.count}>
        {filtered.length} {filtered.length === 1 ? "avatar" : "avatars"}
      </Text>
    </View>
  );

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load("initial")}
      loadingLabel="Loading avatars…"
    >
      <FlatList
        data={filtered}
        keyExtractor={keyExtractor}
        renderItem={renderItem}
        numColumns={2}
        columnWrapperStyle={styles.column}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        ListEmptyComponent={
          <Text style={styles.empty}>
            {avatars.length === 0
              ? "No avatars are available yet. Create one from a photo above."
              : "No avatars match your search."}
          </Text>
        }
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void load("refresh")}
            tintColor={colors.accent}
          />
        }
        keyboardShouldPersistTaps="handled"
      />
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 48 },
  header: { gap: 12, marginBottom: 12 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  cta: {
    backgroundColor: colors.card,
    borderColor: colors.primary,
    borderWidth: 1,
    borderStyle: "dashed",
    borderRadius: 12,
    padding: 14,
    alignItems: "center",
  },
  ctaText: { color: colors.primary, fontSize: 14, fontWeight: "700" },
  search: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  count: { color: colors.muted, fontSize: 12, fontWeight: "600" },
  column: { gap: 12 },
  tile: {
    flex: 1,
    marginBottom: 12,
    gap: 8,
  },
  thumbBox: {
    aspectRatio: 1,
    borderRadius: 14,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  thumb: { width: "100%", height: "100%" },
  thumbEmpty: { color: colors.muted, fontSize: 32, fontWeight: "700" },
  badge: {
    position: "absolute",
    top: 8,
    left: 8,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  badgeCustom: { borderColor: colors.primary },
  badgeText: { color: colors.textSecondary, fontSize: 10, fontWeight: "700" },
  name: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  empty: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
    paddingVertical: 24,
    textAlign: "center",
  },
});
