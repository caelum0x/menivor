/**
 * Model Catalog — live model compare.
 *
 * Calls GET /catalog/models/compare for a chosen capability, sorted by price or
 * latency, and renders each reviewed listing with its price and the provider's
 * rolling health (uptime + state). Tap a row for the full model detail; use
 * "Add to estimate" to drop a model into the pre-render cost estimator (keyed
 * on its capability as the pipeline stage).
 *
 * NAV MANIFEST (routes for the integration agent to wire into navigation):
 *   { route: "/catalog/model-catalog",  title: "Model Catalog" }
 *   { route: "/catalog/provider-health", title: "Provider Health" }
 *   { route: "/catalog/quote",           title: "Estimate Cost" }
 *   { route: "/catalog/presets",         title: "Motion & VFX" }
 *   { route: "/catalog/model/[id]",      title: "Model" }
 *
 * Route: /catalog/model-catalog
 */

import type { ReactElement } from "react";
import { useCallback, useState } from "react";
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { CatalogList } from "@/components/catalog/CatalogList";
import { HealthBadge } from "@/components/catalog/HealthBadge";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import {
  compareModels,
  formatUsdMicros,
  type CompareModel,
  type CompareSort,
} from "@/lib/marketplace";
import { useQuoteDraft } from "@/lib/model-quote";

const CAPABILITIES: readonly string[] = [
  "script",
  "voice",
  "avatar",
  "broll",
  "image",
  "music",
];

const SORTS: readonly { id: CompareSort; label: string }[] = [
  { id: "price", label: "Cheapest" },
  { id: "latency", label: "Fastest" },
];

function priceLabel(model: CompareModel): string {
  const micros = model.price?.unit_price_micros;
  if (micros == null) return "Price on quote";
  const unit = model.price?.unit || model.metering_unit || "unit";
  return `${formatUsdMicros(micros)} / ${unit}`;
}

export default function ModelCatalogScreen(): ReactElement {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { draft, addStage } = useQuoteDraft();

  const [capability, setCapability] = useState<string>("script");
  const [sort, setSort] = useState<CompareSort>("price");

  const fetcher = useCallback(
    () => compareModels(capability, sort, { token }),
    [capability, sort, token],
  );
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<CompareModel[]>(fetcher);

  const items = data ?? [];

  const onAddToEstimate = useCallback(
    (model: CompareModel) => {
      const stage = model.capability || capability;
      Alert.alert(
        "Add to estimate",
        `Use "${model.display_name || model.model_id}" for the ${stage} stage of your cost estimate?`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Add",
            onPress: () => {
              void addStage(stage, model.model_id).then(() => {
                Alert.alert("Added", `Saved for the ${stage} stage. Open Estimate cost to price it.`);
              });
            },
          },
        ],
      );
    },
    [addStage, capability],
  );

  const renderItem = useCallback(
    (model: CompareModel): ReactElement => {
      const inEstimate = draft.stages[model.capability || capability] === model.model_id;
      return (
        <Pressable
          style={styles.card}
          accessibilityRole="button"
          onPress={() => router.push(`/catalog/model/${encodeURIComponent(model.model_id)}`)}
        >
          <View style={styles.cardHead}>
            <Text style={styles.name} numberOfLines={1}>
              {model.display_name || model.model_id}
            </Text>
            <HealthBadge
              state={model.health?.state}
              uptime={model.health?.uptime}
              samples={model.health?.samples}
            />
          </View>
          <Text style={styles.sub} numberOfLines={1}>
            {model.provider?.display_name || model.provider?.provider_key || "—"}
            {model.latency_band ? ` · ${model.latency_band}` : ""}
            {model.availability_state ? ` · ${model.availability_state}` : ""}
          </Text>
          <View style={styles.cardFoot}>
            <Text style={styles.price}>{priceLabel(model)}</Text>
            <Pressable
              style={[styles.addBtn, inEstimate && styles.addBtnActive]}
              onPress={() => onAddToEstimate(model)}
              accessibilityRole="button"
              hitSlop={6}
            >
              <Text style={[styles.addText, inEstimate && styles.addTextActive]}>
                {inEstimate ? "In estimate" : "Add to estimate"}
              </Text>
            </Pressable>
          </View>
        </Pressable>
      );
    },
    [draft.stages, capability, onAddToEstimate, router],
  );

  const header = (
    <View style={styles.controls}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.chipRow}
      >
        {CAPABILITIES.map((cap) => {
          const active = cap === capability;
          return (
            <Pressable
              key={cap}
              onPress={() => setCapability(cap)}
              style={[styles.chip, active && styles.chipActive]}
              accessibilityRole="button"
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>{cap}</Text>
            </Pressable>
          );
        })}
      </ScrollView>

      <View style={styles.sortRow}>
        {SORTS.map((s) => {
          const active = s.id === sort;
          return (
            <Pressable
              key={s.id}
              onPress={() => setSort(s.id)}
              style={[styles.sortBtn, active && styles.sortBtnActive]}
              accessibilityRole="button"
            >
              <Text style={[styles.sortText, active && styles.sortTextActive]}>{s.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <View style={styles.linkRow}>
        <Pressable onPress={() => router.push("/catalog/provider-health")} hitSlop={6}>
          <Text style={styles.link}>Provider health</Text>
        </Pressable>
        <Pressable onPress={() => router.push("/catalog/quote")} hitSlop={6}>
          <Text style={styles.link}>Estimate cost</Text>
        </Pressable>
        <Pressable onPress={() => router.push("/catalog/presets")} hitSlop={6}>
          <Text style={styles.link}>Motion &amp; VFX</Text>
        </Pressable>
      </View>
    </View>
  );

  return (
    <CatalogList<CompareModel>
      status={status}
      error={error}
      items={items}
      keyExtractor={(m) => m.model_id}
      renderItem={renderItem}
      onRetry={reload}
      refreshing={refreshing}
      onRefresh={refresh}
      intro="Compare reviewed models for a capability by price and provider health. Tap a model for details, or add it to a cost estimate."
      header={header}
      emptyTitle="No models for this capability"
      emptyBody="No reviewed listings are live for this capability yet. Try another capability or pull to refresh."
      loadingLabel="Comparing models…"
    />
  );
}

const styles = StyleSheet.create({
  controls: { gap: 12, marginBottom: 8 },
  chipRow: { gap: 8, paddingRight: 8 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { color: colors.textSecondary, fontSize: 13, textTransform: "capitalize" },
  chipTextActive: { color: colors.bg, fontWeight: "700" },
  sortRow: { flexDirection: "row", gap: 8 },
  sortBtn: {
    flex: 1,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 8,
    alignItems: "center",
  },
  sortBtnActive: { borderColor: colors.accent },
  sortText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  sortTextActive: { color: colors.accent, fontWeight: "700" },
  linkRow: { flexDirection: "row", flexWrap: "wrap", gap: 16 },
  link: { color: colors.accent, fontSize: 13, fontWeight: "700" },
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
  sub: { color: colors.muted, fontSize: 12, textTransform: "capitalize" },
  cardFoot: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  price: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  addBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  addBtnActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  addText: { color: colors.textSecondary, fontSize: 12, fontWeight: "700" },
  addTextActive: { color: colors.bg },
});
