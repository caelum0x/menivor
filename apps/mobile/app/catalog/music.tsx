/**
 * Music Library catalog — browse the licensed background tracks from
 * GET /catalog/music. Filter by name, see each track's duration, and pick one
 * for your next reel (persisted locally as `music_id`).
 *
 * Route: /catalog/music
 */

import type { ReactElement } from "react";
import { useCallback, useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors } from "@/components/me/theme";
import { CatalogList } from "@/components/catalog/CatalogList";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import { listMusic, useCatalogSelection, type MusicTrack } from "@/lib/catalog";

function formatTrackDuration(seconds: number | undefined): string {
  if (!seconds || !Number.isFinite(seconds) || seconds <= 0) return "—";
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export default function MusicCatalogScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { selection, patch } = useCatalogSelection();
  const [query, setQuery] = useState("");

  const fetcher = useCallback(() => listMusic({ token }), [token]);
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<MusicTrack[]>(fetcher);

  const selectedId = selection.musicId;

  const items = useMemo<MusicTrack[]>(() => {
    const all = data ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.filename ?? "").toLowerCase().includes(q),
    );
  }, [data, query]);

  const onToggle = useCallback(
    async (track: MusicTrack) => {
      // Tapping the picked track again clears it (no track).
      await patch({ musicId: track.id === selectedId ? "" : track.id });
    },
    [patch, selectedId],
  );

  const renderItem = useCallback(
    (track: MusicTrack): ReactElement => {
      const isSelected = track.id === selectedId;
      return (
        <View style={[styles.card, isSelected && styles.cardSelected]}>
          <View style={styles.info}>
            <Text style={styles.name} numberOfLines={1}>
              {track.name}
            </Text>
            <Text style={styles.meta} numberOfLines={1}>
              {formatTrackDuration(track.duration_s)} · {track.filename || track.id}
            </Text>
          </View>
          <Pressable
            style={[styles.pickBtn, isSelected && styles.pickBtnActive]}
            onPress={() => void onToggle(track)}
            accessibilityRole="button"
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
    <TextInput
      style={styles.search}
      placeholder="Search tracks…"
      placeholderTextColor={colors.muted}
      value={query}
      onChangeText={setQuery}
      autoCapitalize="none"
      autoCorrect={false}
    />
  );

  return (
    <CatalogList<MusicTrack>
      status={status}
      error={error}
      items={items}
      keyExtractor={(t) => t.id}
      renderItem={renderItem}
      onRetry={reload}
      refreshing={refreshing}
      onRefresh={refresh}
      intro="Licensed background tracks. Pick one to sit under your reel — tap Picked again to remove it."
      header={header}
      emptyTitle={query ? "No matching tracks" : "No music yet"}
      emptyBody={
        query
          ? "No tracks match your search. Try a different term."
          : "The music catalog returned nothing. Pull to refresh to try again."
      }
      loadingLabel="Loading music…"
    />
  );
}

const styles = StyleSheet.create({
  search: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 15,
    marginBottom: 14,
  },
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
  info: { flex: 1, gap: 3 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  meta: { color: colors.muted, fontSize: 12 },
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
