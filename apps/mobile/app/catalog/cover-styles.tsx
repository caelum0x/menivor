/**
 * Cover Styles catalog — browse the cover/thumbnail treatments from
 * GET /catalog/cover-styles. Each row renders a live mini-preview using the
 * style's accent/background/text colours over a sample headline, and can be
 * picked for your next reel's cover (persisted locally as `cover_style`).
 *
 * Route: /catalog/cover-styles
 */

import type { ReactElement } from "react";
import { useCallback, useMemo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { CatalogList } from "@/components/catalog/CatalogList";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import { listCoverStyles, useCatalogSelection, type CoverStyle } from "@/lib/catalog";

const SAMPLE_HEADLINE = "THE ONE TRICK NOBODY TOLD YOU";

function CoverPreview({ style }: { style: CoverStyle }): ReactElement {
  const background = style.background ?? "#111114";
  const text = style.text ?? "#ffffff";
  const accent = style.accent ?? colors.accent;
  return (
    <View style={[styles.preview, { backgroundColor: background }]}>
      <View style={[styles.accentBar, { backgroundColor: accent }]} />
      <Text style={[styles.previewHeadline, { color: text }]} numberOfLines={3}>
        {SAMPLE_HEADLINE}
      </Text>
    </View>
  );
}

export default function CoverStylesScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { selection, patch } = useCatalogSelection();

  const fetcher = useCallback(() => listCoverStyles({ token }), [token]);
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<CoverStyle[]>(fetcher);

  const items = useMemo<CoverStyle[]>(() => data ?? [], [data]);
  const selectedId = selection.coverStyle;

  const onPick = useCallback(
    async (style: CoverStyle) => {
      await patch({ coverStyle: style.id });
    },
    [patch],
  );

  const renderItem = useCallback(
    (style: CoverStyle): ReactElement => {
      const isSelected = style.id === selectedId;
      return (
        <Pressable
          style={[styles.card, isSelected && styles.cardSelected]}
          onPress={() => void onPick(style)}
          accessibilityRole="button"
        >
          <CoverPreview style={style} />
          <View style={styles.body}>
            <View style={styles.head}>
              <Text style={styles.name}>{style.name}</Text>
              {isSelected ? <Text style={styles.selectedTag}>Picked</Text> : null}
            </View>
            {style.description ? <Text style={styles.desc}>{style.description}</Text> : null}
            <View style={styles.swatchRow}>
              {style.background ? (
                <View style={[styles.swatch, { backgroundColor: style.background }]} />
              ) : null}
              {style.accent ? (
                <View style={[styles.swatch, { backgroundColor: style.accent }]} />
              ) : null}
              {style.text ? (
                <View style={[styles.swatch, { backgroundColor: style.text }]} />
              ) : null}
              <Text style={styles.id}>{style.id}</Text>
            </View>
          </View>
        </Pressable>
      );
    },
    [onPick, selectedId],
  );

  return (
    <CatalogList<CoverStyle>
      status={status}
      error={error}
      items={items}
      keyExtractor={(s) => s.id}
      renderItem={renderItem}
      onRetry={reload}
      refreshing={refreshing}
      onRefresh={refresh}
      intro="Cover treatments overlay your hook as a bold headline on the poster frame. The mini-preview shows the colours; tap one to pick it for your reel's cover."
      emptyTitle="No cover styles"
      emptyBody="The cover-style catalog returned nothing. Pull to refresh to try again."
      loadingLabel="Loading cover styles…"
    />
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
    flexDirection: "row",
    gap: 14,
  },
  cardSelected: { borderColor: colors.accent },
  preview: {
    width: 74,
    height: 118,
    borderRadius: 8,
    padding: 8,
    justifyContent: "flex-end",
    overflow: "hidden",
  },
  accentBar: { position: "absolute", top: 8, left: 8, width: 26, height: 5, borderRadius: 3 },
  previewHeadline: { fontSize: 12, fontWeight: "900", lineHeight: 14 },
  body: { flex: 1, gap: 5, paddingVertical: 2 },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  name: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  selectedTag: { color: colors.accent, fontSize: 12, fontWeight: "700" },
  desc: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  swatchRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 },
  swatch: { width: 16, height: 16, borderRadius: 4, borderColor: colors.border, borderWidth: 1 },
  id: { color: colors.muted, fontSize: 11, marginLeft: 4 },
});
