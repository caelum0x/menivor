/**
 * SPARK input form: the creator describes their app/niche and picks how many
 * concepts to generate and in which language. Presentational + local input
 * state only — the parent (`app/ideas.tsx`) owns the network call and passes
 * `loading` for the submit affordance.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  DEFAULT_IDEA_COUNT,
  MAX_IDEA_COUNT,
  MIN_IDEA_COUNT,
  type GenerateIdeasRequest,
  type Language,
} from "@/lib/types";

import { colors } from "@/components/me/theme";

const LANGUAGES: readonly Language[] = ["auto", "tr", "en"];
const COUNTS: readonly number[] = [3, 6, 10];

interface IdeaFormProps {
  loading: boolean;
  onGenerate: (req: GenerateIdeasRequest) => void;
}

export function IdeaForm({ loading, onGenerate }: IdeaFormProps) {
  const [appContext, setAppContext] = useState("");
  const [audience, setAudience] = useState("");
  const [count, setCount] = useState<number>(DEFAULT_IDEA_COUNT);
  const [language, setLanguage] = useState<Language>("auto");

  const trimmed = appContext.trim();
  const canSubmit = trimmed.length > 0 && !loading;

  const submit = () => {
    if (!canSubmit) return;
    const clamped = Math.max(MIN_IDEA_COUNT, Math.min(MAX_IDEA_COUNT, count));
    onGenerate({
      app_context: trimmed,
      audience: audience.trim() || undefined,
      count: clamped,
      language,
    });
  };

  return (
    <View style={styles.form}>
      <Text style={styles.label}>Describe your app or niche</Text>
      <TextInput
        style={styles.input}
        value={appContext}
        onChangeText={setAppContext}
        placeholder="e.g. A budgeting app for freelancers in Turkey"
        placeholderTextColor={colors.muted}
        maxLength={1000}
        multiline
        editable={!loading}
      />

      <Text style={styles.label}>Audience (optional)</Text>
      <TextInput
        style={styles.inputShort}
        value={audience}
        onChangeText={setAudience}
        placeholder="e.g. 20-35 year old freelancers"
        placeholderTextColor={colors.muted}
        maxLength={300}
        editable={!loading}
      />

      <Text style={styles.label}>How many ideas</Text>
      <View style={styles.chips}>
        {COUNTS.map((c) => {
          const active = c === count;
          return (
            <Pressable
              key={c}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => setCount(c)}
              disabled={loading}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>
                {c}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <Text style={styles.label}>Language</Text>
      <View style={styles.chips}>
        {LANGUAGES.map((l) => {
          const active = l === language;
          return (
            <Pressable
              key={l}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => setLanguage(l)}
              disabled={loading}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>
                {l}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <Pressable
        style={[styles.primary, !canSubmit && styles.disabled]}
        onPress={submit}
        disabled={!canSubmit}
      >
        {loading ? (
          <ActivityIndicator color={colors.textPrimary} />
        ) : (
          <Text style={styles.primaryText}>Generate ideas</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  form: { gap: 8 },
  label: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "700",
    marginTop: 8,
  },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    minHeight: 72,
    textAlignVertical: "top",
  },
  inputShort: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary },
  chipTextActive: { color: colors.textPrimary, fontWeight: "700" },
  primary: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 16,
  },
  disabled: { opacity: 0.5 },
  primaryText: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
});
