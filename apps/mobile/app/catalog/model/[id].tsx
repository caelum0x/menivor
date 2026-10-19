/**
 * Model detail — GET /catalog/models/{id}.
 *
 * The full reviewed listing for one model: provider, region, data policy,
 * latency band, availability, supported inputs, output limits, and the active
 * price breakdown (unit price, min charge, flat fee). "Add to estimate" drops
 * the model into the pre-render cost estimator keyed on its capability.
 *
 * Route: /catalog/model/[id]
 */

import type { ReactElement } from "react";
import { useCallback } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { HealthBadge } from "@/components/catalog/HealthBadge";
import { useResource } from "@/components/me/use-resource";
import { useSession } from "@/src/shared/auth";
import {
  formatUsdMicros,
  getCatalogModelDetail,
  type CatalogModelDetail,
} from "@/lib/marketplace";
import { useQuoteDraft } from "@/lib/model-quote";

function first(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

interface FactRowProps {
  label: string;
  value: string;
}

function FactRow({ label, value }: FactRowProps): ReactElement {
  return (
    <View style={styles.factRow}>
      <Text style={styles.factLabel}>{label}</Text>
      <Text style={styles.factValue}>{value || "—"}</Text>
    </View>
  );
}

export default function ModelDetailScreen(): ReactElement {
  const router = useRouter();
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const modelId = first(params.id);
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { draft, addStage } = useQuoteDraft();

  const fetcher = useCallback(
    () => getCatalogModelDetail(modelId, { token }),
    [modelId, token],
  );
  const { status, data, error, reload } = useResource<CatalogModelDetail>(fetcher);

  const onAddToEstimate = useCallback(
    (model: CatalogModelDetail) => {
      const stage = model.capability || "stage";
      Alert.alert(
        "Add to estimate",
        `Use "${model.display_name || model.model_id}" for the ${stage} stage of your cost estimate?`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Add",
            onPress: () => {
              void addStage(stage, model.model_id).then(() => {
                Alert.alert("Added", `Saved for the ${stage} stage.`, [
                  { text: "Keep browsing", style: "cancel" },
                  { text: "Open estimate", onPress: () => router.push("/catalog/quote") },
                ]);
              });
            },
          },
        ],
      );
    },
    [addStage, router],
  );

  const title = data?.display_name || (modelId ? modelId : "Model");

  if (status === "loading") {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: "Model" }} />
        <ActivityIndicator color={colors.accent} />
        <Text style={styles.muted}>Loading model…</Text>
      </View>
    );
  }

  if (status === "error" || !data) {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: "Model" }} />
        <Text style={styles.errorText}>{error || "This model could not be loaded."}</Text>
        <Pressable style={styles.retry} onPress={reload} accessibilityRole="button">
          <Text style={styles.retryText}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  const model = data;
  const inEstimate = draft.stages[model.capability] === model.model_id;
  const price = model.price ?? {};
  const outputLimitKeys = Object.keys(model.output_limits ?? {});

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title }} />

      <View style={styles.headerRow}>
        <Text style={styles.title}>{title}</Text>
        <HealthBadge state={model.provider?.health_state} />
      </View>
      <Text style={styles.modelId}>{model.model_id}</Text>
      {model.description ? <Text style={styles.desc}>{model.description}</Text> : null}

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Listing</Text>
        <FactRow label="Capability" value={model.capability} />
        <FactRow label="Availability" value={model.availability_state} />
        <FactRow label="Release" value={model.release_status} />
        <FactRow label="Latency band" value={model.latency_band} />
        <FactRow label="Metering unit" value={model.metering_unit} />
        <FactRow label="Region" value={model.region} />
        <FactRow label="Data policy" value={model.data_policy} />
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Provider</Text>
        <FactRow
          label="Name"
          value={model.provider?.display_name || model.provider?.provider_key || ""}
        />
        <FactRow label="Key" value={model.provider?.provider_key || ""} />
        <FactRow label="Region" value={model.provider?.region || ""} />
        <FactRow label="Data policy" value={model.provider?.data_policy || ""} />
        <FactRow label="Health" value={model.provider?.health_state || "unknown"} />
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Active price</Text>
        <FactRow
          label="Unit price"
          value={
            price.unit_price_micros != null
              ? `${formatUsdMicros(price.unit_price_micros)} / ${price.unit || model.metering_unit}`
              : ""
          }
        />
        <FactRow
          label="Min charge"
          value={price.min_charge_micros ? formatUsdMicros(price.min_charge_micros) : "—"}
        />
        <FactRow
          label="Flat fee"
          value={price.flat_fee_micros ? formatUsdMicros(price.flat_fee_micros) : "—"}
        />
        <FactRow label="Currency" value={price.currency || "USD"} />
        <FactRow label="Price version" value={price.version != null ? `v${price.version}` : ""} />
      </View>

      {model.supported_inputs && model.supported_inputs.length > 0 ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Supported inputs</Text>
          <View style={styles.tagRow}>
            {model.supported_inputs.map((input) => (
              <View key={input} style={styles.tag}>
                <Text style={styles.tagText}>{input}</Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      {outputLimitKeys.length > 0 ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Output limits</Text>
          {outputLimitKeys.map((key) => (
            <FactRow
              key={key}
              label={key}
              value={String((model.output_limits as Record<string, unknown>)[key])}
            />
          ))}
        </View>
      ) : null}

      <Pressable
        style={[styles.primary, inEstimate && styles.primaryDone]}
        onPress={() => onAddToEstimate(model)}
        accessibilityRole="button"
      >
        <Text style={[styles.primaryText, inEstimate && styles.primaryDoneText]}>
          {inEstimate ? "In your estimate" : "Add to estimate"}
        </Text>
      </Pressable>

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  centered: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
  },
  muted: { color: colors.muted, fontSize: 13 },
  errorText: { color: colors.error, fontSize: 14, textAlign: "center" },
  retry: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  retryText: { color: colors.textSecondary, fontWeight: "600" },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  title: { color: colors.textPrimary, fontSize: 20, fontWeight: "800", flex: 1 },
  modelId: { color: colors.muted, fontSize: 12, fontFamily: "monospace", marginTop: 4 },
  desc: { color: colors.textSecondary, fontSize: 14, lineHeight: 20, marginTop: 10 },
  section: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginTop: 14,
    gap: 8,
  },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1,
    marginBottom: 2,
  },
  factRow: { flexDirection: "row", justifyContent: "space-between", gap: 12 },
  factLabel: { color: colors.textSecondary, fontSize: 13 },
  factValue: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: "600",
    flexShrink: 1,
    textAlign: "right",
    textTransform: "capitalize",
  },
  tagRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  tag: {
    backgroundColor: colors.cardAlt,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  tagText: { color: colors.textSecondary, fontSize: 12, fontWeight: "500" },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: "center",
    marginTop: 18,
  },
  primaryDone: { backgroundColor: colors.card, borderColor: colors.accent, borderWidth: 1 },
  primaryText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  primaryDoneText: { color: colors.accent },
  spacer: { height: 32 },
});
