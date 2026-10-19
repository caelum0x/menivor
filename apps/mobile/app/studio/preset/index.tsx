/**
 * Studio · Preset Shelf
 *
 * Nav manifest:
 *   { route: "/studio/preset",      title: "Preset Shelf" }
 *   { route: "/studio/preset/[id]", title: "Preset" }
 *
 * THE GAP THIS CLOSES: the web app has had a one-tap "tap a preset, type a
 * topic (or add a photo), see the price, make it" flow since MH2
 * (apps/web/src/features/presets-shelf, GET/POST /presets/shelf/*). Mobile had
 * no client for that domain at all — a mobile creator who liked a preset had
 * to leave the gallery and walk the full multi-step Create wizard instead of
 * tapping one tile and making it, same as Higgsfield's mobile app does for
 * its own template shelf. This screen ports the already-tested web flow to
 * Expo using the same backend endpoints, no new backend code.
 *
 * Browse the public preset shelf (GET /presets/shelf, no sign-in needed to
 * browse) and tap one to open the one-tap generate screen.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
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

import { listShelf, type PresetTile } from "@/lib/presets-shelf";
import { registerScreen } from "@/lib/nav/registry";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";

registerScreen({
  route: "/studio/preset",
  title: "Preset Shelf",
  subtitle: "Tap a preset, add your topic or a photo, and see the price before you make it",
  group: "Core",
  groupOrder: 1,
  order: 19.5,
  keywords: ["presets", "shelf", "one tap", "effects", "filters", "template"],
});

export default function StudioPresetShelfScreen() {
  const router = useRouter();

  const [tiles, setTiles] = useState<readonly PresetTile[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");

  const load = useCallback(async (mode: "initial" | "refresh") => {
    if (mode === "initial") setStatus("loading");
    else setRefreshing(true);
    try {
      const shelf = await listShelf();
      setTiles(shelf);
      setStatus("ready");
      setError("");
    } catch (err) {
      setError(describeError(err, "Failed to load the preset shelf."));
      if (mode === "initial") setStatus("error");
    } finally {
      if (mode === "refresh") setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load("initial");
  }, [load]);

  const onRefresh = useCallback(() => {
    void load("refresh");
  }, [load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tiles;
    return tiles.filter((t) =>
      [t.name, t.blurb].join(" ").toLowerCase().includes(q),
    );
  }, [tiles, search]);

  const openTile = useCallback(
    (id: string) => router.push(`/studio/preset/${encodeURIComponent(id)}`),
    [router],
  );

  const keyExtractor = useCallback((t: PresetTile) => t.id, []);

  const renderItem = useCallback(
    ({ item }: { item: PresetTile }) => (
      <Pressable
        style={styles.card}
        onPress={() => openTile(item.id)}
        accessibilityRole="button"
      >
        <Image
          source={{ uri: item.preview.poster_url }}
          style={styles.poster}
          resizeMode="cover"
          accessibilityLabel={`${item.name} preview`}
        />
        <View style={styles.cardBody}>
          <Text style={styles.name}>{item.name}</Text>
          <Text style={styles.desc} numberOfLines={2}>
            {item.blurb}
          </Text>
          <Text style={styles.meta}>
            {item.credit_label}
            {item.inputs.includes("image") ? " · needs a photo" : ""}
          </Text>
        </View>
      </Pressable>
    ),
    [openTile],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        One preset, one input, one button. Tap a tile, add your topic or a
        photo, see the price, then make it — the same fast path the web app's
        preset shelf uses.
      </Text>
      <TextInput
        style={styles.search}
        value={search}
        onChangeText={setSearch}
        placeholder="Search presets"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
      />
      <Text style={styles.count}>
        {filtered.length} {filtered.length === 1 ? "preset" : "presets"}
      </Text>
    </View>
  );

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load("initial")}
      loadingLabel="Loading presets…"
    >
      <FlatList
        data={filtered}
        keyExtractor={keyExtractor}
        renderItem={renderItem}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={Separator}
        ListEmptyComponent={
          <Text style={styles.empty}>
            {tiles.length === 0
              ? "No presets are available right now."
              : "No presets match your search."}
          </Text>
        }
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
        keyboardShouldPersistTaps="handled"
      />
    </StudioScreen>
  );
}

function Separator() {
  return <View style={styles.sep} />;
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 48 },
  header: { gap: 12, marginBottom: 12 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
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
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    overflow: "hidden",
    flexDirection: "row",
  },
  poster: { width: 84, height: 84, backgroundColor: colors.bg },
  cardBody: { flex: 1, padding: 12, gap: 4, justifyContent: "center" },
  name: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  desc: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  meta: { color: colors.muted, fontSize: 12 },
  sep: { height: 10 },
  empty: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
    paddingVertical: 24,
    textAlign: "center",
  },
});
