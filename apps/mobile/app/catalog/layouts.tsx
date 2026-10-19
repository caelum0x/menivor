/**
 * Layouts catalog — browse the composition layouts from GET /catalog/layouts
 * (picture-in-picture, split screen, full frame…). Each row draws a small 9:16
 * schematic of how the avatar and screen recording are arranged, and can be
 * picked for your next reel (persisted locally as `layout`).
 *
 * Route: /catalog/layouts
 */

import type { ReactElement } from "react";
import { useCallback, useMemo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { CatalogList } from "@/components/catalog/CatalogList";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import { listLayouts, useCatalogSelection, type LayoutOption } from "@/lib/catalog";

/** A tiny 9:16 schematic hinting at how the layout arranges its two sources. */
function LayoutSchematic({ id }: { id: string }): ReactElement {
  const key = id.toLowerCase();
  const isSplit = key.includes("split");
  const isPip = key.includes("pip") || key.includes("picture");
  const isFull = key.includes("full") || key.includes("solo") || key.includes("single");

  return (
    <View style={styles.frame}>
      {isSplit ? (
        <>
          <View style={[styles.half, { borderBottomColor: colors.border, borderBottomWidth: 1 }]} />
          <View style={styles.half} />
        </>
      ) : isPip ? (
        <>
          <View style={styles.bg} />
          <View style={styles.pip} />
        </>
      ) : isFull ? (
        <View style={styles.bg} />
      ) : (
        <>
          <View style={[styles.bg, { flex: 2 }]} />
          <View style={[styles.strip, { flex: 1 }]} />
        </>
      )}
    </View>
  );
}

export default function LayoutsCatalogScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { selection, patch } = useCatalogSelection();

  const fetcher = useCallback(() => listLayouts({ token }), [token]);
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<LayoutOption[]>(fetcher);

  const items = useMemo<LayoutOption[]>(() => data ?? [], [data]);
  const selectedId = selection.layout;

  const onPick = useCallback(
    async (layout: LayoutOption) => {
      await patch({ layout: String(layout.id) });
    },
    [patch],
  );

  const renderItem = useCallback(
    (layout: LayoutOption): ReactElement => {
      const id = String(layout.id);
      const isSelected = id === selectedId;
      return (
        <Pressable
          style={[styles.card, isSelected && styles.cardSelected]}
          onPress={() => void onPick(layout)}
          accessibilityRole="button"
        >
          <LayoutSchematic id={id} />
          <View style={styles.body}>
            <View style={styles.head}>
              <Text style={styles.name}>{layout.name}</Text>
              {isSelected ? <Text style={styles.selectedTag}>Picked</Text> : null}
            </View>
            {layout.description ? (
              <Text style={styles.desc}>{layout.description}</Text>
            ) : null}
            <Text style={styles.id}>{id}</Text>
          </View>
        </Pressable>
      );
    },
    [onPick, selectedId],
  );

  return (
    <CatalogList<LayoutOption>
      status={status}
      error={error}
      items={items}
      keyExtractor={(l) => String(l.id)}
      renderItem={renderItem}
      onRetry={reload}
      refreshing={refreshing}
      onRefresh={refresh}
      intro="How the avatar and your screen recording share the 9:16 frame. Tap a layout to pick it for your next reel."
      emptyTitle="No layouts"
      emptyBody="The layout catalog returned nothing. Pull to refresh to try again."
      loadingLabel="Loading layouts…"
    />
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
    flexDirection: "row",
    gap: 14,
    alignItems: "center",
  },
  cardSelected: { borderColor: colors.accent },
  frame: {
    width: 42,
    height: 74,
    borderRadius: 6,
    borderColor: colors.border,
    borderWidth: 1,
    overflow: "hidden",
    backgroundColor: colors.cardAlt,
  },
  bg: { flex: 1, backgroundColor: colors.cardAlt },
  half: { flex: 1, backgroundColor: colors.cardAlt },
  strip: { backgroundColor: colors.border },
  pip: {
    position: "absolute",
    right: 5,
    bottom: 5,
    width: 15,
    height: 20,
    borderRadius: 3,
    backgroundColor: colors.accent,
  },
  body: { flex: 1, gap: 4 },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  name: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  selectedTag: { color: colors.accent, fontSize: 12, fontWeight: "700" },
  desc: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  id: { color: colors.muted, fontSize: 11 },
});
