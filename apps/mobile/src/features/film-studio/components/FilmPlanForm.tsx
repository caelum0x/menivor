/**
 * Film / Series setup form — collect the beat sheet + lead character, then plan
 * and persist a project in one call (`POST /film/projects`). The create is
 * idempotency-keyed so a transport retry cannot double-create. On 503 the
 * backend's persistence layer is unavailable; that surfaces as an inline error.
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
import { ApiError } from "@/src/shared/api";
import {
  createFilmProject,
  type FilmProjectSummary,
} from "@/lib/film";

import {
  buildCreateProjectBody,
  createProjectIdempotencyKey,
  missingProjectFields,
  type FilmStudioFormInput,
} from "../logic";

interface FilmPlanFormProps {
  token: string | undefined;
  onCreated: (summary: FilmProjectSummary) => void;
  /** Return to the saved-projects list without creating anything. */
  onCancel?: () => void;
}

const DEFAULT_TOTAL_SHOTS = 12;

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 503) {
      return "Film persistence is unavailable right now. Try again shortly.";
    }
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "Could not create the project.";
}

export function FilmPlanForm({ token, onCreated, onCancel }: FilmPlanFormProps) {
  const [title, setTitle] = React.useState("");
  const [characterId, setCharacterId] = React.useState("");
  const [characterName, setCharacterName] = React.useState("");
  const [descriptors, setDescriptors] = React.useState("");
  const [style, setStyle] = React.useState("");
  const [beatsText, setBeatsText] = React.useState("");
  const [totalShots, setTotalShots] = React.useState(String(DEFAULT_TOTAL_SHOTS));
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const form: FilmStudioFormInput = {
    title,
    characterId,
    characterName,
    descriptors,
    style,
    beatsText,
    totalShots: Number.parseInt(totalShots, 10) || DEFAULT_TOTAL_SHOTS,
  };
  const missing = missingProjectFields(form);
  const ready = missing.length === 0 && !submitting;

  const submit = React.useCallback(async () => {
    if (missingProjectFields(form).length > 0 || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const body = buildCreateProjectBody(form);
      const summary = await createFilmProject(
        body,
        createProjectIdempotencyKey(),
        { token },
      );
      onCreated(summary);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }, [form, onCreated, submitting, token]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Break your story into beats and lock a lead character. We plan an
        identity-consistent shot list and persist it as a project you can render
        shot by shot.
      </Text>

      <Text style={styles.label}>Project title</Text>
      <TextInput
        style={styles.input}
        value={title}
        onChangeText={setTitle}
        placeholder="Neon Heist — Episode 1"
        placeholderTextColor={colors.muted}
        editable={!submitting}
      />

      <Text style={styles.label}>Character id</Text>
      <TextInput
        style={styles.input}
        value={characterId}
        onChangeText={setCharacterId}
        placeholder="lead_01"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        editable={!submitting}
      />

      <Text style={styles.label}>Character name</Text>
      <TextInput
        style={styles.input}
        value={characterName}
        onChangeText={setCharacterName}
        placeholder="Mara Vance"
        placeholderTextColor={colors.muted}
        editable={!submitting}
      />

      <Text style={styles.label}>Descriptors (comma or newline separated)</Text>
      <TextInput
        style={[styles.input, styles.multiline]}
        value={descriptors}
        onChangeText={setDescriptors}
        placeholder="red trench coat, silver hair, cyber-noir"
        placeholderTextColor={colors.muted}
        multiline
        editable={!submitting}
      />

      <Text style={styles.label}>Style (optional)</Text>
      <TextInput
        style={styles.input}
        value={style}
        onChangeText={setStyle}
        placeholder="cinematic, high-contrast"
        placeholderTextColor={colors.muted}
        editable={!submitting}
      />

      <Text style={styles.label}>Beats — one per line, "scene_id | summary"</Text>
      <TextInput
        style={[styles.input, styles.beats]}
        value={beatsText}
        onChangeText={setBeatsText}
        placeholder={"s1 | Mara breaks into the vault\ns2 | Alarms trip, she runs"}
        placeholderTextColor={colors.muted}
        multiline
        editable={!submitting}
      />

      <Text style={styles.label}>Target shot count</Text>
      <TextInput
        style={styles.input}
        value={totalShots}
        onChangeText={setTotalShots}
        placeholder={String(DEFAULT_TOTAL_SHOTS)}
        placeholderTextColor={colors.muted}
        keyboardType="number-pad"
        editable={!submitting}
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <Pressable
        style={[styles.button, !ready && styles.buttonDisabled]}
        onPress={submit}
        disabled={!ready}
      >
        {submitting ? (
          <ActivityIndicator color={colors.bg} />
        ) : (
          <Text style={styles.buttonText}>Plan &amp; create project</Text>
        )}
      </Pressable>

      {missing.length > 0 ? (
        <Text style={styles.hint}>Still needed: {missing.join(", ")}</Text>
      ) : null}
      {onCancel ? (
        <Pressable onPress={onCancel} accessibilityRole="button" style={styles.cancel}>
          <Text style={styles.cancelText}>Back to your films</Text>
        </Pressable>
      ) : null}
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  cancel: { marginTop: 16, alignSelf: "center" },
  cancelText: { color: colors.primary, fontSize: 14, fontWeight: "700" },
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  label: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: "600",
    marginBottom: 6,
  },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    color: colors.textPrimary,
    fontSize: 14,
    marginBottom: 12,
  },
  multiline: { minHeight: 64, textAlignVertical: "top" },
  beats: { minHeight: 120, textAlignVertical: "top" },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 13,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 4,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  hint: { color: colors.muted, fontSize: 12, marginTop: 10, textAlign: "center" },
  error: { color: colors.error, fontSize: 14, marginBottom: 10 },
  spacer: { height: 32 },
});
