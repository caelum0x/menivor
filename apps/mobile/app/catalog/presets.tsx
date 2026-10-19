/**
 * Motion & VFX presets — GET /catalog/motion-presets + GET /catalog/vfx-presets.
 *
 * Browse the one-click camera-motion presets and the stackable cinematic VFX
 * (Effects Mix) the render pipeline can apply. Toggle between the two catalogs;
 * the VFX view shows the Effects-Mix stack cap. Read-only reference surface.
 *
 * Route: /catalog/presets
 */

import type { ReactElement } from "react";
import { useCallback, useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { CatalogList } from "@/components/catalog/CatalogList";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import {
  listMotionPresets,
  listVfxPresets,
  type MotionPreset,
  type VfxPreset,
} from "@/lib/marketplace";

type Kind = "motion" | "vfx";

interface PresetsPayload {
  motion: MotionPreset[];
  vfx: VfxPreset[];
  maxStack: number;
}

export default function PresetsScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [kind, setKind] = useState<Kind>("motion");

  const fetcher = useCallback(async (): Promise<PresetsPayload> => {
    const [motion, vfxResult] = await Promise.all([
      listMotionPresets({ token }),
      listVfxPresets({ token }),
    ]);
    return { motion, vfx: vfxResult.vfx, maxStack: vfxResult.maxStack };
  }, [token]);

  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<PresetsPayload>(fetcher);

  const items = useMemo<(MotionPreset | VfxPreset)[]>(() => {
    if (!data) return [];
    return kind === "motion" ? data.motion : data.vfx;
  }, [data, kind]);

  const renderItem = useCallback((preset: MotionPreset | VfxPreset): ReactElement => {
    return (
      <View style={styles.card}>
        <View style={styles.cardHead}>
          <Text style={styles.name}>{preset.name}</Text>
          <Text style={styles.id}>{preset.id}</Text>
        </View>
        {preset.description ? (
          <Text style={styles.desc}>{preset.description}</Text>
        ) : null}
        {preset.tags && preset.tags.length > 0 ? (
          <View style={styles.tagRow}>
            {preset.tags.map((tag) => (
              <View key={tag} style={styles.tag}>
                <Text style={styles.tagText}>{tag}</Text>
              </View>
            ))}
          </View>
        ) : null}
      </View>
    );
  }, []);

  const header = (
    <View style={styles.controls}>
      <View style={styles.toggleRow}>
        <Pressable
          onPress={() => setKind("motion")}
          style={[styles.toggle, kind === "motion" && styles.toggleActive]}
          accessibilityRole="button"
        >
          <Text style={[styles.toggleText, kind === "motion" && styles.toggleTextActive]}>
            Camera motion
          </Text>
        </Pressable>
        <Pressable
          onPress={() => setKind("vfx")}
          style={[styles.toggle, kind === "vfx" && styles.toggleActive]}
          accessibilityRole="button"
        >
          <Text style={[styles.toggleText, kind === "vfx" && styles.toggleTextActive]}>VFX</Text>
        </Pressable>
      </View>
      {kind === "vfx" && data ? (
        <Text style={styles.stackHint}>
          Effects Mix — stack up to {data.maxStack} VFX in one shot.
        </Text>
      ) : null}
    </View>
  );

  return (
    <CatalogList<MotionPreset | VfxPreset>
      status={status}
      error={error}
      items={items}
      keyExtractor={(p) => p.id}
      renderItem={renderItem}
      onRetry={reload}
      refreshing={refreshing}
      onRefresh={refresh}
      intro="One-click camera moves and stackable cinematic VFX the render pipeline can apply to a reel."
      header={header}
      emptyTitle="No presets"
      emptyBody="This preset catalog is empty right now. Pull to refresh to try again."
      loadingLabel="Loading presets…"
    />
  );
}

const styles = StyleSheet.create({
  controls: { gap: 10, marginBottom: 8 },
  toggleRow: { flexDirection: "row", gap: 8 },
  toggle: {
    flex: 1,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 9,
    alignItems: "center",
  },
  toggleActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  toggleText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  toggleTextActive: { color: colors.bg, fontWeight: "700" },
  stackHint: { color: colors.muted, fontSize: 12 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    gap: 8,
  },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "700", flex: 1 },
  id: { color: colors.muted, fontSize: 11, fontFamily: "monospace" },
  desc: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  tagRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  tag: {
    backgroundColor: colors.cardAlt,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  tagText: { color: colors.textSecondary, fontSize: 12, fontWeight: "500" },
});
