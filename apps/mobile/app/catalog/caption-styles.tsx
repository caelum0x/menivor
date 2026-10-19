/**
 * Caption Styles catalog — browse the burned-in subtitle presets from
 * GET /catalog/caption-styles. Each row previews the style's spoken/upcoming
 * word colours (ASS `&HAABBGGRR` → CSS) over a sample caption. Tap a style to
 * open a full preview and pick it for your next reel (persisted locally as
 * `caption_style`).
 *
 * Route: /catalog/caption-styles
 */

import type { ReactElement } from "react";
import { useCallback, useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { CatalogList } from "@/components/catalog/CatalogList";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import { assColorToCss } from "@/src/features/reel-create/components/caption-colors";
import { listCaptionStyles, useCatalogSelection, type CaptionStyle } from "@/lib/catalog";

function CaptionPreview({ style }: { style: CaptionStyle }): ReactElement {
  const spoken = assColorToCss(style.primary);
  const upcoming = assColorToCss(style.secondary, colors.textSecondary);
  return (
    <View style={styles.previewStage}>
      <Text style={styles.previewLine}>
        <Text style={[styles.previewWord, { color: spoken }]}>THIS </Text>
        <Text style={[styles.previewWord, { color: spoken }]}>IS </Text>
        <Text style={[styles.previewWord, { color: upcoming }]}>your </Text>
        <Text style={[styles.previewWord, { color: upcoming }]}>caption</Text>
      </Text>
    </View>
  );
}

export default function CaptionStylesScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { selection, patch } = useCatalogSelection();
  const [active, setActive] = useState<CaptionStyle | null>(null);

  const fetcher = useCallback(() => listCaptionStyles({ token }), [token]);
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<CaptionStyle[]>(fetcher);

  const items = useMemo<CaptionStyle[]>(() => data ?? [], [data]);
  const selectedId = selection.captionStyle;

  const onPick = useCallback(
    async (style: CaptionStyle) => {
      await patch({ captionStyle: style.id });
      setActive(null);
    },
    [patch],
  );

  const renderItem = useCallback(
    (style: CaptionStyle): ReactElement => {
      const spoken = assColorToCss(style.primary);
      const upcoming = assColorToCss(style.secondary, colors.textSecondary);
      const isSelected = style.id === selectedId;
      return (
        <Pressable
          style={[styles.card, isSelected && styles.cardSelected]}
          onPress={() => setActive(style)}
          accessibilityRole="button"
        >
          <View style={styles.cardHead}>
            <Text style={styles.name}>{style.name}</Text>
            {isSelected ? <Text style={styles.selectedTag}>Picked</Text> : null}
          </View>
          {style.description ? <Text style={styles.desc}>{style.description}</Text> : null}
          <View style={styles.swatchRow}>
            <View style={[styles.swatch, { backgroundColor: spoken }]} />
            <View style={[styles.swatch, { backgroundColor: upcoming }]} />
            <Text style={styles.swatchLabel}>spoken / upcoming</Text>
          </View>
        </Pressable>
      );
    },
    [selectedId],
  );

  return (
    <>
      <CatalogList<CaptionStyle>
        status={status}
        error={error}
        items={items}
        keyExtractor={(s) => s.id}
        renderItem={renderItem}
        onRetry={reload}
        refreshing={refreshing}
        onRefresh={refresh}
        intro="Every style burns subtitles into the video. The two swatches are the colour of the word being spoken and the words coming next."
        emptyTitle="No caption styles"
        emptyBody="The caption-style catalog returned nothing. Pull to refresh to try again."
        loadingLabel="Loading caption styles…"
      />

      <Modal
        visible={active !== null}
        transparent
        animationType="slide"
        onRequestClose={() => setActive(null)}
      >
        <View style={styles.modalScrim}>
          <View style={styles.modalSheet}>
            {active ? (
              <ScrollView contentContainerStyle={styles.modalContent}>
                <Text style={styles.modalName}>{active.name}</Text>
                {active.description ? (
                  <Text style={styles.modalDesc}>{active.description}</Text>
                ) : null}
                <CaptionPreview style={active} />
                <View style={styles.metaRow}>
                  <Text style={styles.metaKey}>Spoken colour</Text>
                  <Text style={styles.metaVal}>{active.primary ?? "default"}</Text>
                </View>
                <View style={styles.metaRow}>
                  <Text style={styles.metaKey}>Upcoming colour</Text>
                  <Text style={styles.metaVal}>{active.secondary ?? "default"}</Text>
                </View>
                <View style={styles.metaRow}>
                  <Text style={styles.metaKey}>Style id</Text>
                  <Text style={styles.metaVal}>{active.id}</Text>
                </View>

                <Pressable
                  style={styles.primaryBtn}
                  onPress={() => void onPick(active)}
                  accessibilityRole="button"
                >
                  <Text style={styles.primaryBtnText}>
                    {active.id === selectedId ? "Picked — keep using" : "Use this style"}
                  </Text>
                </Pressable>
                <Pressable
                  style={styles.secondaryBtn}
                  onPress={() => setActive(null)}
                  accessibilityRole="button"
                >
                  <Text style={styles.secondaryBtnText}>Close</Text>
                </Pressable>
              </ScrollView>
            ) : null}
          </View>
        </View>
      </Modal>
    </>
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
    gap: 8,
  },
  cardSelected: { borderColor: colors.accent },
  cardHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  name: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  selectedTag: { color: colors.accent, fontSize: 12, fontWeight: "700" },
  desc: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  swatchRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  swatch: { width: 22, height: 22, borderRadius: 5, borderColor: colors.border, borderWidth: 1 },
  swatchLabel: { color: colors.muted, fontSize: 12, marginLeft: 4 },

  modalScrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", justifyContent: "flex-end" },
  modalSheet: {
    backgroundColor: colors.bg,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    borderColor: colors.border,
    borderWidth: 1,
    maxHeight: "88%",
  },
  modalContent: { padding: 20, gap: 12 },
  modalName: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  modalDesc: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  previewStage: {
    backgroundColor: "#000000",
    borderRadius: 12,
    paddingVertical: 40,
    paddingHorizontal: 16,
    alignItems: "center",
    marginVertical: 4,
  },
  previewLine: { textAlign: "center" },
  previewWord: { fontSize: 24, fontWeight: "900", letterSpacing: 0.5 },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
    paddingVertical: 8,
  },
  metaKey: { color: colors.muted, fontSize: 13 },
  metaVal: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  primaryBtn: {
    backgroundColor: colors.accent,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 8,
  },
  primaryBtnText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  secondaryBtn: { borderColor: colors.border, borderWidth: 1, borderRadius: 10, paddingVertical: 12, alignItems: "center" },
  secondaryBtnText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
});
