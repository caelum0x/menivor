/**
 * Studio · Template Gallery
 *
 * Nav manifest (for the integration agent to wire into navigation):
 *   { route: "/studio/templates",         title: "Template Studio" }
 *   { route: "/studio/template/[slug]",   title: "Template Preview" }
 *
 * Browse the seeded genre shot-templates (GET /templates) and, when the
 * analytics layer is up, a ranked "Most used" strip (GET
 * /templates/analytics/popular) so creators can start from what actually
 * converts. Search by name/genre/tag, filter by genre, pull-to-refresh. Each
 * card opens the compile-preview detail (/studio/template/[slug]) where the
 * template's resolved output can be previewed before instantiating.
 *
 * Explicit loading / error (retry) / empty states. The popular strip degrades
 * silently to nothing when its DB layer is unavailable (503).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
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
  getPopularTemplates,
  listTemplates,
  type PopularTemplate,
  type TemplateSummary,
} from "@/lib/templates";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { FilterChips } from "@/components/studio/FilterChips";
import { StudioScreen } from "@/components/studio/StudioScreen";

const ALL_GENRES = "__all__";

function genreOf(t: TemplateSummary): string {
  return (t.genre || "").trim();
}

export default function StudioTemplatesScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [popular, setPopular] = useState<PopularTemplate[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [genre, setGenre] = useState<string>(ALL_GENRES);

  const load = useCallback(
    async (mode: "initial" | "refresh") => {
      if (mode === "initial") setStatus("loading");
      else setRefreshing(true);
      try {
        // The gallery is required; the popular strip is best-effort and must
        // never fail the page (it 503s when analytics is down).
        const [gallery, ranked] = await Promise.all([
          listTemplates({ token }),
          getPopularTemplates({ token }).catch(() => [] as PopularTemplate[]),
        ]);
        setTemplates(gallery.templates);
        setPopular(ranked);
        setStatus("ready");
        setError("");
      } catch (err) {
        setError(describeError(err, "Failed to load templates."));
        if (mode === "initial") setStatus("error");
      } finally {
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  const onRefresh = useCallback(() => {
    void load("refresh");
  }, [load]);

  useEffect(() => {
    void load("initial");
  }, [load]);

  const genres = useMemo(() => {
    const set = new Set<string>();
    for (const t of templates) {
      const g = genreOf(t);
      if (g) set.add(g);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [templates]);

  const filterOptions = useMemo(
    () => [
      { id: ALL_GENRES, label: "All" },
      ...genres.map((g) => ({ id: g, label: g })),
    ],
    [genres],
  );

  const nameBySlug = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of templates) map.set(t.slug, t.name);
    return map;
  }, [templates]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return templates.filter((t) => {
      if (genre !== ALL_GENRES && genreOf(t) !== genre) return false;
      if (!q) return true;
      const haystack = [t.name, t.genre, t.description, ...t.tags]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [templates, search, genre]);

  const rankedPopular = useMemo(
    () =>
      popular
        .filter((p) => nameBySlug.has(p.template_slug))
        .slice(0, 8),
    [popular, nameBySlug],
  );

  const openTemplate = useCallback(
    (slug: string) => router.push(`/studio/template/${encodeURIComponent(slug)}`),
    [router],
  );

  const keyExtractor = useCallback((t: TemplateSummary) => t.slug, []);

  const renderItem = useCallback(
    ({ item }: { item: TemplateSummary }) => (
      <Pressable
        style={styles.card}
        onPress={() => openTemplate(item.slug)}
        accessibilityRole="button"
      >
        <Text style={styles.name}>{item.name}</Text>
        <Text style={styles.desc} numberOfLines={2}>
          {item.description}
        </Text>
        <Text style={styles.meta}>
          {item.genre} · {item.aspect} · {item.min_duration_s}–
          {item.max_duration_s}s · {item.slot_count} shots
          {item.loopable ? " · loop" : ""}
        </Text>
      </Pressable>
    ),
    [openTemplate],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        Pick a proven viral format, then preview its compiled shot-plan before
        you build. Each template resolves the hook, pacing, captions and audio
        for you.
      </Text>

      {rankedPopular.length > 0 ? (
        <View style={styles.popular}>
          <Text style={styles.sectionLabel}>Most used</Text>
          <View style={styles.popularRow}>
            {rankedPopular.map((p, index) => (
              <Pressable
                key={p.template_slug}
                style={styles.popularChip}
                onPress={() => openTemplate(p.template_slug)}
                accessibilityRole="button"
              >
                <Text style={styles.popularRank}>{index + 1}</Text>
                <Text style={styles.popularName} numberOfLines={1}>
                  {nameBySlug.get(p.template_slug) ?? p.template_slug}
                </Text>
                <Text style={styles.popularCount}>
                  {p.count} {p.count === 1 ? "build" : "builds"}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>
      ) : null}

      <TextInput
        style={styles.search}
        value={search}
        onChangeText={setSearch}
        placeholder="Search templates"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
      />
      {genres.length > 0 ? (
        <FilterChips
          options={filterOptions}
          selected={genre}
          onSelect={setGenre}
        />
      ) : null}
      <Text style={styles.count}>
        {filtered.length} {filtered.length === 1 ? "template" : "templates"}
      </Text>
    </View>
  );

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load("initial")}
      loadingLabel="Loading templates…"
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
            {templates.length === 0
              ? "No templates are available right now."
              : "No templates match your search."}
          </Text>
        }
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
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
  popular: { gap: 8 },
  sectionLabel: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  popularRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  popularChip: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 2,
    minWidth: 132,
    flexGrow: 1,
  },
  popularRank: {
    color: colors.accent,
    fontSize: 11,
    fontWeight: "800",
  },
  popularName: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  popularCount: { color: colors.muted, fontSize: 11 },
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
    padding: 14,
    gap: 6,
  },
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
