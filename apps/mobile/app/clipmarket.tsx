/**
 * ClipMarket screen — browse active pay-per-view campaigns and launch a new one
 * on mobile. Mirrors the web `/clipmarket` dashboard.
 */

import * as React from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import {
  createCampaign,
  formatUsdMicros,
  listCampaigns,
  type Campaign,
} from "@/lib/clipmarket";

const USD_TO_MICROS = 1_000_000;

export default function ClipMarketScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [campaigns, setCampaigns] = React.useState<Campaign[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const [title, setTitle] = React.useState("");
  const [cpm, setCpm] = React.useState("");
  const [budget, setBudget] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [formError, setFormError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const res = await listCampaigns({ token });
      setCampaigns(res.campaigns);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load campaigns.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await listCampaigns({ token });
        if (active) setCampaigns(res.campaigns);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Failed to load campaigns.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [token]);

  const onCreate = React.useCallback(async () => {
    setFormError("");
    const cpmUsd = Number(cpm);
    const budgetUsd = Number(budget);
    if (!Number.isFinite(cpmUsd) || cpmUsd <= 0) {
      setFormError("Enter a valid CPM in USD.");
      return;
    }
    if (!Number.isFinite(budgetUsd) || budgetUsd <= 0) {
      setFormError("Enter a valid budget in USD.");
      return;
    }
    setSubmitting(true);
    try {
      await createCampaign(
        {
          title: title.trim() || undefined,
          cpm_micros: Math.round(cpmUsd * USD_TO_MICROS),
          budget_micros: Math.round(budgetUsd * USD_TO_MICROS),
        },
        { token },
      );
      setTitle("");
      setCpm("");
      setBudget("");
      setLoading(true);
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create campaign.");
    } finally {
      setSubmitting(false);
    }
  }, [title, cpm, budget, token, load]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Pay creators per view. Launch a campaign, set your CPM and budget, and track spend.
      </Text>

      <View style={styles.card}>
        <Text style={styles.formTitle}>New campaign</Text>
        <TextInput
          style={styles.input}
          placeholder="Title (optional)"
          placeholderTextColor={colors.muted}
          value={title}
          onChangeText={setTitle}
        />
        <TextInput
          style={styles.input}
          placeholder="CPM (USD per 1k views)"
          placeholderTextColor={colors.muted}
          keyboardType="decimal-pad"
          value={cpm}
          onChangeText={setCpm}
        />
        <TextInput
          style={styles.input}
          placeholder="Budget (USD)"
          placeholderTextColor={colors.muted}
          keyboardType="decimal-pad"
          value={budget}
          onChangeText={setBudget}
        />
        {formError ? <Text style={styles.error}>{formError}</Text> : null}
        <Pressable
          style={[styles.button, submitting && styles.buttonDisabled]}
          onPress={onCreate}
          disabled={submitting}
        >
          {submitting ? (
            <ActivityIndicator color={colors.bg} />
          ) : (
            <Text style={styles.buttonText}>Launch campaign</Text>
          )}
        </Pressable>
      </View>

      <Text style={styles.sectionTitle}>Active campaigns</Text>
      {loading ? (
        <ActivityIndicator color={colors.primary} style={styles.spacer} />
      ) : error ? (
        <Text style={styles.error}>{error}</Text>
      ) : campaigns.length === 0 ? (
        <Text style={styles.empty}>No campaigns yet — launch your first one above.</Text>
      ) : (
        campaigns.map((c) => (
          <View key={c.id} style={styles.card}>
            <Text style={styles.name}>{c.title || "Untitled campaign"}</Text>
            <Text style={styles.meta}>
              {formatUsdMicros(c.cpm_micros)} CPM · {c.status}
            </Text>
            <Text style={styles.spend}>
              {formatUsdMicros(c.spent_micros)} / {formatUsdMicros(c.budget_micros)} spent
            </Text>
          </View>
        ))
      )}
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  formTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "600", marginBottom: 12 },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "600",
    marginTop: 8,
    marginBottom: 12,
  },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 14,
    marginBottom: 10,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 4,
  },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { color: colors.bg, fontSize: 15, fontWeight: "600" },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  name: { color: colors.textPrimary, fontSize: 16, fontWeight: "600", marginBottom: 4 },
  meta: { color: colors.textSecondary, fontSize: 13, marginBottom: 6 },
  spend: { color: colors.muted, fontSize: 12 },
  empty: { color: colors.muted, fontSize: 14 },
  error: { color: colors.error, fontSize: 14, marginBottom: 8 },
  spacer: { height: 24 },
});
