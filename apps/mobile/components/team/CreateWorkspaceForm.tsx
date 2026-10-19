/**
 * Create form for a new team workspace -> POST /workspaces. Just a name plus a
 * submit; owns its own submitting/error state and clears on success. The parent
 * performs the create (so it can prepend the new workspace to its list).
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

import type { CreateWorkspaceRequest } from "@/lib/types";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";

interface CreateWorkspaceFormProps {
  /** Performs the create; resolves once the new workspace is in the list. */
  onCreate: (body: CreateWorkspaceRequest) => Promise<void>;
}

export function CreateWorkspaceForm({ onCreate }: CreateWorkspaceFormProps) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = !!name.trim() && !submitting;

  const onSubmit = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Give your workspace a name.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onCreate({ name: trimmed });
      setName("");
    } catch (err) {
      setError(describeError(err, "Failed to create workspace."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.label}>New workspace</Text>
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          value={name}
          onChangeText={(text) => {
            setName(text);
            if (error) setError(null);
          }}
          placeholder="e.g. Acme Studio"
          placeholderTextColor={colors.muted}
          editable={!submitting}
          returnKeyType="done"
          onSubmitEditing={() => {
            if (canSubmit) void onSubmit();
          }}
        />
        <Pressable
          style={[styles.button, !canSubmit && styles.buttonDisabled]}
          onPress={onSubmit}
          disabled={!canSubmit}
          accessibilityRole="button"
          accessibilityLabel="Create workspace"
          accessibilityState={{ disabled: !canSubmit }}
        >
          {submitting ? (
            <ActivityIndicator color={colors.textPrimary} />
          ) : (
            <Text style={styles.buttonText}>Create</Text>
          )}
        </Pressable>
      </View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
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
  label: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  row: { flexDirection: "row", gap: 8, alignItems: "center" },
  input: {
    flex: 1,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingHorizontal: 18,
    paddingVertical: 11,
    alignItems: "center",
    justifyContent: "center",
    minWidth: 92,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.textPrimary, fontWeight: "700" },
  error: { color: colors.error, fontSize: 13 },
});
