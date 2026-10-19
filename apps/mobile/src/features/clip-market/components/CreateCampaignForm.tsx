/**
 * CreateCampaignForm — the brand's "launch a campaign" form. Owns its own input
 * state and client-side validation via `parseCampaignForm`; hands a valid
 * {@link CreateCampaignBody} up to the screen, which performs the real POST.
 */

import * as React from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import type { CreateCampaignBody } from "@/lib/clipmarket";

import { parseCampaignForm } from "../logic";

export interface CreateCampaignFormProps {
  submitting?: boolean;
  onSubmit: (body: CreateCampaignBody) => void;
}

export function CreateCampaignForm({
  submitting = false,
  onSubmit,
}: CreateCampaignFormProps) {
  const [title, setTitle] = React.useState("");
  const [cpmUsd, setCpmUsd] = React.useState("");
  const [budgetUsd, setBudgetUsd] = React.useState("");
  const [minViews, setMinViews] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const onLaunch = React.useCallback(() => {
    const result = parseCampaignForm({ title, cpmUsd, budgetUsd, minViews });
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setError(null);
    onSubmit(result.value);
  }, [title, cpmUsd, budgetUsd, minViews, onSubmit]);

  return (
    <View style={styles.card}>
      <Text style={styles.title}>New campaign</Text>
      <TextInput
        style={styles.input}
        placeholder="Title (optional)"
        placeholderTextColor={colors.muted}
        value={title}
        onChangeText={setTitle}
        testID="campaign-title"
      />
      <TextInput
        style={styles.input}
        placeholder="CPM (USD per 1k views)"
        placeholderTextColor={colors.muted}
        keyboardType="decimal-pad"
        value={cpmUsd}
        onChangeText={setCpmUsd}
        testID="campaign-cpm"
      />
      <TextInput
        style={styles.input}
        placeholder="Budget (USD)"
        placeholderTextColor={colors.muted}
        keyboardType="decimal-pad"
        value={budgetUsd}
        onChangeText={setBudgetUsd}
        testID="campaign-budget"
      />
      <TextInput
        style={styles.input}
        placeholder="Minimum views (optional)"
        placeholderTextColor={colors.muted}
        keyboardType="number-pad"
        value={minViews}
        onChangeText={setMinViews}
        testID="campaign-min-views"
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        style={[styles.button, submitting && styles.disabled]}
        onPress={onLaunch}
        disabled={submitting}
        accessibilityRole="button"
        testID="campaign-launch"
      >
        {submitting ? (
          <ActivityIndicator color={colors.bg} />
        ) : (
          <Text style={styles.buttonText}>Launch campaign</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 10,
  },
  title: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 14,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 2,
  },
  disabled: { opacity: 0.6 },
  buttonText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  error: { color: colors.error, fontSize: 13 },
});
