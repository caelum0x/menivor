/**
 * Templates catalog — browse the curated job templates from
 * GET /catalog/templates. Each template pre-fills a whole reel brief (subject,
 * prompt scaffold, layout, caption style, language, duration). Tap for the full
 * brief, then pick it — picking also applies the template's layout and caption
 * style to your saved picks (persisted locally as `template_id`, `layout`,
 * `caption_style`).
 *
 * Route: /catalog/templates
 */

import type { ReactElement } from "react";
import { useCallback, useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { CatalogList } from "@/components/catalog/CatalogList";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import {
  listCatalogTemplates,
  useCatalogSelection,
  type CatalogTemplate,
} from "@/lib/catalog";

function MetaRow({ label, value }: { label: string; value: string }): ReactElement {
  return (
    <View style={styles.metaRow}>
      <Text style={styles.metaKey}>{label}</Text>
      <Text style={styles.metaVal}>{value}</Text>
    </View>
  );
}

export default function TemplatesCatalogScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { selection, patch } = useCatalogSelection();
  const [active, setActive] = useState<CatalogTemplate | null>(null);

  const fetcher = useCallback(() => listCatalogTemplates({ token }), [token]);
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<CatalogTemplate[]>(fetcher);

  const items = useMemo<CatalogTemplate[]>(() => data ?? [], [data]);
  const selectedId = selection.templateId;

  const onPick = useCallback(
    async (tpl: CatalogTemplate) => {
      await patch({
        templateId: tpl.id,
        layout: String(tpl.layout),
        captionStyle: tpl.caption_style,
      });
      setActive(null);
    },
    [patch],
  );

  const renderItem = useCallback(
    (tpl: CatalogTemplate): ReactElement => {
      const isSelected = tpl.id === selectedId;
      return (
        <Pressable
          style={[styles.card, isSelected && styles.cardSelected]}
          onPress={() => setActive(tpl)}
          accessibilityRole="button"
        >
          <View style={styles.head}>
            <Text style={styles.name}>{tpl.name}</Text>
            {isSelected ? <Text style={styles.selectedTag}>Picked</Text> : null}
          </View>
          {tpl.description ? <Text style={styles.desc}>{tpl.description}</Text> : null}
          <Text style={styles.tagline}>
            {String(tpl.layout)} · {tpl.language} · {tpl.target_duration_s}s
          </Text>
        </Pressable>
      );
    },
    [selectedId],
  );

  return (
    <>
      <CatalogList<CatalogTemplate>
        status={status}
        error={error}
        items={items}
        keyExtractor={(t) => t.id}
        renderItem={renderItem}
        onRetry={reload}
        refreshing={refreshing}
        onRefresh={refresh}
        intro="Curated starting points. Each pre-fills a full reel brief so you can compose in one tap. Open one to read the brief before picking."
        emptyTitle="No templates"
        emptyBody="The template catalog returned nothing. Pull to refresh to try again."
        loadingLabel="Loading templates…"
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

                <Text style={styles.blockLabel}>Video subject</Text>
                <Text style={styles.blockBody}>{active.video_subject || "—"}</Text>

                <Text style={styles.blockLabel}>Prompt scaffold</Text>
                <Text style={styles.blockBody}>{active.prompt_scaffold || "—"}</Text>

                <MetaRow label="Layout" value={String(active.layout)} />
                <MetaRow label="Caption style" value={active.caption_style || "default"} />
                <MetaRow label="Language" value={String(active.language)} />
                <MetaRow label="Target duration" value={`${active.target_duration_s}s`} />
                <MetaRow label="Template id" value={active.id} />

                <Pressable
                  style={styles.primaryBtn}
                  onPress={() => void onPick(active)}
                  accessibilityRole="button"
                >
                  <Text style={styles.primaryBtnText}>
                    {active.id === selectedId ? "Picked — keep using" : "Use this template"}
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
    gap: 6,
  },
  cardSelected: { borderColor: colors.accent },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  name: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  selectedTag: { color: colors.accent, fontSize: 12, fontWeight: "700" },
  desc: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  tagline: { color: colors.muted, fontSize: 12 },

  modalScrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", justifyContent: "flex-end" },
  modalSheet: {
    backgroundColor: colors.bg,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    borderColor: colors.border,
    borderWidth: 1,
    maxHeight: "88%",
  },
  modalContent: { padding: 20, gap: 10 },
  modalName: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  modalDesc: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  blockLabel: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1,
    marginTop: 8,
  },
  blockBody: { color: colors.textPrimary, fontSize: 14, lineHeight: 20 },
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
    marginTop: 12,
  },
  primaryBtnText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  secondaryBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  secondaryBtnText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
});
