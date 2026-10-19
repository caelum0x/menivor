/**
 * Studio · Motion Presets — camera-move gallery.
 *
 * Nav manifest:
 *   { route: "/studio/motion",         title: "Motion Presets" }
 *   { route: "/studio/motion/history", title: "Compile History" }
 *   { route: "/studio/motion/[id]",    title: "Motion Preset" }
 *
 * The real, versioned camera-move catalog (GET /motion) — the >=50 moves the
 * ReelForge renderer can drive — as a searchable, filterable list with
 * pull-to-refresh. Filter by render class (all / FFmpeg-only / model / hybrid),
 * search by name / tag / description, and tap a card to open its detail where
 * it can be compiled against one of your reels. A header CTA deep-links to the
 * caller's compile history. Explicit loading / error / empty states.
 *
 * This replaces the client-only effects-lab demo (which never touched the
 * motion API) with a real, API-backed surface.
 */

import { useCallback, useMemo, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import {
  listMotions,
  type MotionSummary,
  type RenderClass,
} from "@/lib/api/motion";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { FilterChips } from "@/components/studio/FilterChips";

type ClassFilter = "all" | RenderClass;

const FILTERS: { id: ClassFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "filter", label: "FFmpeg" },
  { id: "model", label: "Model" },
  { id: "hybrid", label: "Hybrid" },
];

/** Human label + accent color for a render class badge. */
function classBadge(cls: RenderClass): { label: string; color: string } {
  switch (cls) {
    case "model":
      return { label: "Model", color: colors.accent };
    case "hybrid":
      return { label: "Hybrid", color: colors.success };
    case "filter":
    default:
      return { label: "FFmpeg", color: colors.textSecondary };
  }
}

export default function StudioMotionScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const [motions, setMotions] = useState<MotionSummary[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [cls, setCls] = useState<ClassFilter>("all");

  const load = useCallback(
    async (mode: "initial" | "refresh") => {
      if (mode === "initial") setStatus("loading");
      else setRefreshing(true);
      try {
        const data = await listMotions({ token });
        setMotions(data);
        setStatus("ready");
        setError("");
      } catch (err) {
        setError(describeError(err, "Failed to load motion presets."));
        if (mode === "initial") setStatus("error");
      } finally {
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return motions.filter((m) => {
      if (cls !== "all" && m.render_class !== cls) return false;
      if (!q) return true;
      return (
        m.name.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q) ||
        m.category.toLowerCase().includes(q) ||
        m.tags.some((t) => t.toLowerCase().includes(q))
      );
    });
  }, [motions, search, cls]);

  const keyExtractor = useCallback((m: MotionSummary) => m.id, []);

  const renderItem = useCallback(
    ({ item }: { item: MotionSummary }) => {
      const badge = classBadge(item.render_class);
      return (
        <Pressable
          style={styles.card}
          onPress={() =>
            router.push({
              pathname: "/studio/motion/[id]",
              params: { id: item.id },
            })
          }
          accessibilityRole="button"
          accessibilityLabel={item.name}
        >
          <View style={styles.cardHead}>
            <Text style={styles.name} numberOfLines={1}>
              {item.name}
            </Text>
            <View style={[styles.badge, { borderColor: badge.color }]}>
              <Text style={[styles.badgeText, { color: badge.color }]}>
                {badge.label}
              </Text>
            </View>
          </View>
          <Text style={styles.category}>{item.category}</Text>
          <Text style={styles.desc} numberOfLines={2}>
            {item.description}
          </Text>
          <View style={styles.metaRow}>
            <Text style={styles.meta}>Default intensity {item.intensity}</Text>
            {item.requires_provider ? (
              <Text style={styles.providerFlag}>Needs provider</Text>
            ) : null}
          </View>
          {item.tags.length > 0 ? (
            <View style={styles.tagRow}>
              {item.tags.slice(0, 4).map((t) => (
                <View key={t} style={styles.tag}>
                  <Text style={styles.tagText}>{t}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </Pressable>
      );
    },
    [router],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        The camera-move catalog the renderer can drive — pure FFmpeg moves,
        model-driven camera control, and hybrids. Open one to compile a
        deterministic plan against a reel.
      </Text>
      <Pressable
        style={styles.cta}
        onPress={() => router.push("/studio/motion/history")}
        accessibilityRole="button"
      >
        <Text style={styles.ctaText}>View your compile history</Text>
      </Pressable>
      <TextInput
        style={styles.search}
        value={search}
        onChangeText={setSearch}
        placeholder="Search moves, tags, categories"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
      />
      <FilterChips
        options={FILTERS}
        selected={cls}
        onSelect={(id) => setCls(id as ClassFilter)}
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
      loadingLabel="Loading motion presets…"
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
            {motions.length === 0
              ? "No motion presets are available yet."
              : "No presets match your search."}
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

function Separator() {
  return <View style={styles.sep} />;
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
  sep: { height: 10 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 6,
  },
  cardHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  },
  name: { flex: 1, color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  badge: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  badgeText: { fontSize: 11, fontWeight: "700" },
  category: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "600",
    letterSpacing: 0.6,
    textTransform: "uppercase",
  },
  desc: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 2,
  },
  meta: { color: colors.muted, fontSize: 12 },
  providerFlag: { color: colors.accent, fontSize: 11, fontWeight: "700" },
  tagRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  tag: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  tagText: { color: colors.textSecondary, fontSize: 11 },
  empty: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
    paddingVertical: 24,
    textAlign: "center",
  },
});
