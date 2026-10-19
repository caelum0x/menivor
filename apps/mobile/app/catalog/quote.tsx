/**
 * Estimate Cost — POST /catalog/quotes/generation.
 *
 * The pre-render quote step. Assemble a stage -> model map (added from the
 * Model Catalog / model detail) or name a generation profile, set an optional
 * budget cap, then request a server-signed price snapshot. The result is shown
 * as a per-stage breakdown with the total and a within-budget check, and is
 * persisted so the compose/create screen can display the estimate.
 *
 * Route: /catalog/quote
 */

import type { ReactElement } from "react";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useFocusEffect, useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { describeError } from "@/components/me/errors";
import { useSession } from "@/src/shared/auth";
import {
  formatUsdMicros,
  requestGenerationQuote,
  type GenerationQuote,
  type GenerationQuoteRequestBody,
} from "@/lib/marketplace";
import { getQuoteDraft, saveLastQuote, useQuoteDraft } from "@/lib/model-quote";

/** Validate an optional USD budget string (blank is allowed = no cap). */
function validateBudget(raw: string): { ok: boolean; message?: string } {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: true };
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) {
    return { ok: false, message: "Budget must be a dollar amount, e.g. 2.50." };
  }
  if (Number(trimmed) <= 0) {
    return { ok: false, message: "Budget must be greater than zero." };
  }
  return { ok: true };
}

export default function QuoteScreen(): ReactElement {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { draft, ready, removeStage, patch, clear, reload } = useQuoteDraft();

  const [profile, setProfile] = useState("");
  const [budget, setBudget] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [quote, setQuote] = useState<GenerationQuote | null>(null);

  // Reload the draft (and hydrate the local inputs from it) whenever the screen
  // regains focus, so stages added elsewhere in the catalog appear here.
  useFocusEffect(
    useCallback(() => {
      void reload();
      void getQuoteDraft().then((d) => {
        setProfile((prev) => (prev ? prev : (d.profile ?? "")));
        setBudget((prev) => (prev ? prev : (d.maxCostUsd ?? "")));
      });
    }, [reload]),
  );

  const stageEntries = Object.entries(draft.stages);
  const hasStages = stageEntries.length > 0;
  const hasProfile = profile.trim().length > 0;
  const canSubmit = (hasStages || hasProfile) && !submitting;

  const onRemoveStage = useCallback(
    (stage: string) => {
      Alert.alert("Remove stage", `Remove "${stage}" from the estimate?`, [
        { text: "Cancel", style: "cancel" },
        { text: "Remove", style: "destructive", onPress: () => void removeStage(stage) },
      ]);
    },
    [removeStage],
  );

  const onClear = useCallback(() => {
    Alert.alert("Clear estimate", "Remove all stages and reset the estimate?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Clear",
        style: "destructive",
        onPress: () => {
          void clear();
          setProfile("");
          setBudget("");
          setQuote(null);
          setError("");
        },
      },
    ]);
  }, [clear]);

  const onSubmit = useCallback(async () => {
    if (submitting) return;
    setError("");

    const budgetCheck = validateBudget(budget);
    if (!budgetCheck.ok) {
      setError(budgetCheck.message ?? "Invalid budget.");
      return;
    }
    if (!hasStages && !hasProfile) {
      setError("Add at least one model, or name a generation profile.");
      return;
    }

    // Persist the scalar inputs onto the draft so they survive navigation.
    await patch({ profile: profile.trim(), maxCostUsd: budget.trim() });

    const body: GenerationQuoteRequestBody = {
      ...(hasProfile ? { profile: profile.trim() } : {}),
      ...(hasStages ? { stages: { ...draft.stages } } : {}),
      ...(budget.trim() ? { max_cost_usd: budget.trim() } : {}),
    };

    setSubmitting(true);
    try {
      const result = await requestGenerationQuote(body, { token });
      setQuote(result);
      await saveLastQuote(result);
    } catch (err) {
      setError(describeError(err, "Could not price this estimate."));
    } finally {
      setSubmitting(false);
    }
  }, [submitting, budget, hasStages, hasProfile, patch, profile, draft.stages, token]);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.intro}>
        Preview the pay-as-you-go cost of your model choices before you render. The server returns
        a signed, versioned quote — the exact amount the wallet reserves for the job.
      </Text>

      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>Stages</Text>
        {(hasStages || hasProfile || budget) && ready ? (
          <Pressable onPress={onClear} hitSlop={8} accessibilityRole="button">
            <Text style={styles.clearLink}>Clear</Text>
          </Pressable>
        ) : null}
      </View>

      {hasStages ? (
        stageEntries.map(([stage, modelId]) => (
          <View key={stage} style={styles.stageCard}>
            <View style={styles.stageInfo}>
              <Text style={styles.stageName}>{stage}</Text>
              <Text style={styles.stageModel} numberOfLines={1}>
                {modelId}
              </Text>
            </View>
            <Pressable
              onPress={() => onRemoveStage(stage)}
              hitSlop={8}
              accessibilityRole="button"
              accessibilityLabel={`Remove ${stage} stage`}
            >
              <Text style={styles.removeText}>Remove</Text>
            </Pressable>
          </View>
        ))
      ) : (
        <View style={styles.emptyCard}>
          <Text style={styles.emptyTitle}>No models added</Text>
          <Text style={styles.emptyBody}>
            Add models from the Model Catalog, or name a generation profile below.
          </Text>
          <Pressable
            style={styles.browseBtn}
            onPress={() => router.push("/catalog/model-catalog")}
            accessibilityRole="button"
          >
            <Text style={styles.browseText}>Open Model Catalog</Text>
          </Pressable>
        </View>
      )}

      <Text style={styles.label}>Generation profile (optional)</Text>
      <TextInput
        style={styles.input}
        value={profile}
        onChangeText={setProfile}
        placeholder="e.g. curated-fast"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        editable={!submitting}
      />

      <Text style={styles.label}>Budget cap (USD, optional)</Text>
      <TextInput
        style={styles.input}
        value={budget}
        onChangeText={setBudget}
        placeholder="e.g. 2.50"
        placeholderTextColor={colors.muted}
        keyboardType="decimal-pad"
        editable={!submitting}
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <Pressable
        style={[styles.primary, !canSubmit && styles.disabled]}
        onPress={onSubmit}
        disabled={!canSubmit}
        accessibilityRole="button"
      >
        {submitting ? (
          <ActivityIndicator color={colors.bg} />
        ) : (
          <Text style={styles.primaryText}>Estimate cost</Text>
        )}
      </Pressable>

      {quote ? (
        <View style={styles.quoteCard}>
          <View style={styles.quoteHead}>
            <Text style={styles.quoteTitle}>Estimate</Text>
            <View
              style={[
                styles.budgetPill,
                { backgroundColor: quote.within_budget ? colors.success : colors.error },
              ]}
            >
              <Text style={styles.budgetPillText}>
                {quote.within_budget ? "Within budget" : "Over budget"}
              </Text>
            </View>
          </View>

          {quote.stages.map((s) => (
            <View key={`${s.stage}-${s.model_id}`} style={styles.quoteStageRow}>
              <View style={styles.quoteStageInfo}>
                <Text style={styles.quoteStage}>{s.stage}</Text>
                <Text style={styles.quoteStageMeta} numberOfLines={1}>
                  {s.provider_key || s.model_id} · {s.quantity_units} {s.unit}
                </Text>
              </View>
              <Text style={styles.quoteStageCost}>{formatUsdMicros(s.cost_micros)}</Text>
            </View>
          ))}

          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>Total (reserved)</Text>
            <Text style={styles.totalValue}>{formatUsdMicros(quote.total_micros)}</Text>
          </View>
          {quote.cap_micros != null ? (
            <Text style={styles.quoteMeta}>Budget cap: {formatUsdMicros(quote.cap_micros)}</Text>
          ) : null}
          <Text style={styles.quoteMeta}>
            Quote {quote.quote_id.slice(0, 8)} · expires {quote.expires_at}
          </Text>

          <Pressable
            style={styles.secondary}
            onPress={() => router.push("/(tabs)/jobs")}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Go to Create</Text>
          </Pressable>
        </View>
      ) : null}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20, marginBottom: 16 },
  sectionHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  clearLink: { color: colors.accent, fontSize: 13, fontWeight: "700" },
  stageCard: {
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
  stageInfo: { flex: 1, gap: 3 },
  stageName: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: "700",
    textTransform: "capitalize",
  },
  stageModel: { color: colors.muted, fontSize: 12, fontFamily: "monospace" },
  removeText: { color: colors.error, fontSize: 13, fontWeight: "600" },
  emptyCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 18,
    gap: 10,
    marginBottom: 10,
  },
  emptyTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  emptyBody: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  browseBtn: {
    alignSelf: "flex-start",
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  browseText: { color: colors.accent, fontSize: 13, fontWeight: "700" },
  label: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: "600",
    marginTop: 14,
    marginBottom: 6,
  },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 11,
    color: colors.textPrimary,
    fontSize: 15,
  },
  error: { color: colors.error, fontSize: 14, marginTop: 12 },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: "center",
    marginTop: 18,
  },
  disabled: { opacity: 0.5 },
  primaryText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  quoteCard: {
    backgroundColor: colors.card,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    marginTop: 18,
    gap: 10,
  },
  quoteHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  quoteTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "800" },
  budgetPill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  budgetPillText: { color: colors.bg, fontSize: 11, fontWeight: "700" },
  quoteStageRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    paddingTop: 10,
  },
  quoteStageInfo: { flex: 1, gap: 2 },
  quoteStage: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: "600",
    textTransform: "capitalize",
  },
  quoteStageMeta: { color: colors.muted, fontSize: 12 },
  quoteStageCost: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  totalRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderTopColor: colors.border,
    borderTopWidth: 1,
    paddingTop: 12,
    marginTop: 2,
  },
  totalLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  totalValue: { color: colors.accent, fontSize: 18, fontWeight: "800" },
  quoteMeta: { color: colors.muted, fontSize: 12 },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 6,
  },
  secondaryText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
  spacer: { height: 32 },
});
