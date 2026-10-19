/**
 * Create form for a saved preset -> POST /me/presets. A preset is a name plus
 * an opaque `config` map that gets spread onto a create-job payload later. On
 * mobile we keep the config lightweight: an optional JSON object typed by the
 * user, validated client-side before submit (defaults to `{}`).
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

import type { PresetCreateRequest, Workspace } from "@/lib/types";

import { WorkspaceSelect } from "@/components/team/WorkspaceSelect";

import { colors } from "./theme";

interface PresetCreateFormProps {
  /** Performs the create; resolves once the new preset is in the list. */
  onCreate: (body: PresetCreateRequest) => Promise<void>;
  /**
   * Workspaces the caller can share this brand kit with. When empty, the
   * "Share to team" picker is hidden and presets stay personal.
   */
  workspaces?: readonly Workspace[];
}

/** Parses the optional config field into a plain object, or throws a message. */
function parseConfig(raw: string): Record<string, unknown> {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error("Config must be valid JSON.");
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Config must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

export function PresetCreateForm({
  onCreate,
  workspaces = [],
}: PresetCreateFormProps) {
  const [name, setName] = useState("");
  const [config, setConfig] = useState("");
  /** Workspace to share this brand kit with; `null` keeps it personal. */
  const [shareWorkspaceId, setShareWorkspaceId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = !!name.trim() && !submitting;

  const onSubmit = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Give your preset a name.");
      return;
    }
    let parsedConfig: Record<string, unknown>;
    try {
      parsedConfig = parseConfig(config);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid config.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await onCreate({
        name: trimmedName,
        config: parsedConfig,
        ...(shareWorkspaceId ? { workspace_id: shareWorkspaceId } : {}),
      });
      setName("");
      setConfig("");
      setShareWorkspaceId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save preset.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.label}>New preset</Text>
      <TextInput
        style={styles.input}
        value={name}
        onChangeText={setName}
        placeholder="Preset name (e.g. My brand kit)"
        placeholderTextColor={colors.muted}
        editable={!submitting}
      />
      <TextInput
        style={[styles.input, styles.multiline]}
        value={config}
        onChangeText={setConfig}
        placeholder={'Optional config JSON, e.g. {"layout":"pip"}'}
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        multiline
        editable={!submitting}
      />
      {workspaces.length > 0 ? (
        <View style={styles.shareBlock}>
          <Text style={styles.subLabel}>Share to team</Text>
          <WorkspaceSelect
            workspaces={workspaces}
            value={shareWorkspaceId}
            onSelect={setShareWorkspaceId}
            disabled={submitting}
            personalLabel="Personal"
          />
          <Text style={styles.hint}>
            {shareWorkspaceId
              ? "Every member of this workspace will see this brand kit."
              : "Only you can see this preset."}
          </Text>
        </View>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        style={[styles.button, !canSubmit && styles.buttonDisabled]}
        onPress={onSubmit}
        disabled={!canSubmit}
      >
        {submitting ? (
          <ActivityIndicator color={colors.textPrimary} />
        ) : (
          <Text style={styles.buttonText}>Save preset</Text>
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
  label: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  subLabel: { color: colors.muted, fontSize: 12, fontWeight: "600" },
  shareBlock: { gap: 8 },
  hint: { color: colors.muted, fontSize: 12, lineHeight: 16 },
  input: {
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  multiline: { minHeight: 60, textAlignVertical: "top" },
  error: { color: colors.error, fontSize: 13 },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: "center",
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
});
