/**
 * Background-footage library — browse the curated loop-able "second-stimulation"
 * clips from GET /templates/backgrounds (gameplay parkour, satisfying ASMR,
 * driving, nature …). Split-screen / loop formats auto-fill one of these when
 * you supply no clip of your own. Filter by category or search, then pick one
 * for your next reel (persisted device-locally as `backgroundId`).
 *
 * NAV MANIFEST (for the integration agent):
 *   { route: "/catalog/backgrounds", title: "Backgrounds" }
 *
 * Route: /catalog/backgrounds
 */

import type { ReactElement } from "react";
import { useCallback, useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { colors } from "@/components/me/theme";
import { CatalogList } from "@/components/catalog/CatalogList";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import { listBackgrounds, useCatalogSelection, type BackgroundClip } from "@/lib/catalog";

/** A human label for a raw category id (e.g. "asmr-satisfying" → "ASMR"). */
function categoryLabel(id: string): string {
  switch (id) {
    case "gameplay":
      return "Gameplay";
    case "asmr-satisfying":
      return "ASMR";
    case "driving":
      return "Driving";
    case "nature":
      return "Nature";
    default:
      return id
        .split(/[-_]/)
        .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : part))
        .join(" ");
  }
}

/** How a background resolves to footage: first-party loop vs. stock query. */
function sourceLabel(source: string): string {
  if (source === "bundled") return "In-house loop";
  if (source === "stock") return "Stock footage";
  return source || "Unknown";
}

const ALL = "__all__";

export default function BackgroundsCatalogScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { selection, patch } = useCatalogSelection();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>(ALL);

  // Fetch the whole library once; category + search filter client-side so
  // switching filters is instant and never re-hits the network.
  const fetcher = useCallback(() => listBackgrounds({ token }), [token]);
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<BackgroundClip[]>(fetcher);

  const selectedId = selection.backgroundId;

  const categories = useMemo<readonly string[]>(() => {
    const all = data ?? [];
    const seen = new Set<string>();
    all.forEach((clip) => {
      if (clip.available && clip.category) seen.add(clip.category);
    });
    return [...seen].sort();
  }, [data]);

  const items = useMemo<BackgroundClip[]>(() => {
    const all = data ?? [];
    const q = query.trim().toLowerCase();
    return all.filter((clip) => {
      // Clips the server reports as unavailable cannot render; never offer them.
      if (!clip.available) return false;
      if (category !== ALL && clip.category !== category) return false;
      if (!q) return true;
      return (
        clip.label.toLowerCase().includes(q) ||
        clip.id.toLowerCase().includes(q) ||
        clip.category.toLowerCase().includes(q)
      );
    });
  }, [data, query, category]);

  const onToggle = useCallback(
    async (clip: BackgroundClip) => {
      // Tapping the picked background again clears it (auto-pick by genre).
      await patch({ backgroundId: clip.id === selectedId ? "" : clip.id });
    },
    [patch, selectedId],
  );

  const renderItem = useCallback(
    (clip: BackgroundClip): ReactElement => {
      const isSelected = clip.id === selectedId;
      return (
        <View style={[styles.card, isSelected && styles.cardSelected]}>
          <View style={styles.info}>
            <View style={styles.head}>
              <Text style={styles.name} numberOfLines={1}>
                {clip.label}
              </Text>
            </View>
            <Text style={styles.meta} numberOfLines={1}>
              {categoryLabel(clip.category)} · {sourceLabel(clip.source)}
              {clip.source === "stock" && clip.provider ? ` · ${clip.provider}` : ""}
            </Text>
            {clip.license_note ? (
              <Text style={styles.license} numberOfLines={2}>
                {clip.license_note}
              </Text>
            ) : null}
            <Text style={styles.id}>{clip.id}</Text>
          </View>
          <Pressable
            style={[styles.pickBtn, isSelected && styles.pickBtnActive]}
            onPress={() => void onToggle(clip)}
            accessibilityRole="button"
            accessibilityState={{ selected: isSelected }}
          >
            <Text style={[styles.pickText, isSelected && styles.pickTextActive]}>
              {isSelected ? "Picked" : "Pick"}
            </Text>
          </Pressable>
        </View>
      );
    },
    [onToggle, selectedId],
  );

  const header = (
    <View style={styles.controls}>
      <TextInput
        style={styles.search}
        placeholder="Search backgrounds…"
        placeholderTextColor={colors.muted}
        value={query}
        onChangeText={setQuery}
        autoCapitalize="none"
        autoCorrect={false}
      />
      {categories.length > 0 ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.filterRow}
        >
          {[ALL, ...categories].map((cat) => {
            const active = cat === category;
            return (
              <Pressable
                key={cat}
                style={[styles.filterChip, active && styles.filterChipActive]}
                onPress={() => setCategory(cat)}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
              >
                <Text style={[styles.filterText, active && styles.filterTextActive]}>
                  {cat === ALL ? "All" : categoryLabel(cat)}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      ) : null}
    </View>
  );

  const filtering = query.trim().length > 0 || category !== ALL;

  return (
    <CatalogList<BackgroundClip>
      status={status}
      error={error}
      items={items}
      keyExtractor={(c) => c.id}
      renderItem={renderItem}
      onRetry={reload}
      refreshing={refreshing}
      onRefresh={refresh}
      intro="Loop-able footage that sits behind split-screen and loop reels. Pick one — tap Picked again to let the pipeline auto-choose by genre."
      header={header}
      emptyTitle={filtering ? "No matching backgrounds" : "No backgrounds yet"}
      emptyBody={
        filtering
          ? "No backgrounds match your filter. Try a different category or search term."
          : "The background library returned nothing. Pull to refresh to try again."
      }
      loadingLabel="Loading backgrounds…"
    />
  );
}

const styles = StyleSheet.create({
  controls: { marginBottom: 14, gap: 12 },
  search: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 15,
  },
  filterRow: { gap: 8, paddingRight: 4 },
  filterChip: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  filterChipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  filterText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  filterTextActive: { color: colors.bg },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  cardSelected: { borderColor: colors.accent },
  info: { flex: 1, gap: 4 },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "600", flexShrink: 1 },
  meta: { color: colors.textSecondary, fontSize: 12 },
  license: { color: colors.muted, fontSize: 11, lineHeight: 15 },
  id: { color: colors.muted, fontSize: 11 },
  pickBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  pickBtnActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  pickText: { color: colors.textSecondary, fontSize: 13, fontWeight: "700" },
  pickTextActive: { color: colors.bg },
});
