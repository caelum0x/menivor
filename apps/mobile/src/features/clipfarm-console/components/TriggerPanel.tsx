/**
 * TriggerPanel — the render-trigger form for one Clipfarm channel. A creator
 * pastes an inline source list (one item per line, optional `title | body`),
 * optional hooks/accounts and cross-post platforms, then triggers ONE real
 * render pass (`POST /series/channels/{id}/run`). The parent screen owns the
 * fetch + the resulting `RunResult.summary()`; this panel is presentation +
 * local field state only, and hands the built `RunChannelInput` up on submit.
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
import type { RunChannelInput } from "@/lib/series";

import {
  PLATFORM_OPTIONS,
  buildRunInput,
  canTriggerRun,
  type PlatformOption,
} from "../logic";

const SOURCE_PLACEHOLDER =
  "AITA for refusing to share my fries | Reddit AITA thread body…\nTIL octopuses have three hearts";

export interface TriggerPanelProps {
  submitting: boolean;
  onSubmit: (input: RunChannelInput) => void;
}

function TriggerPanelBase({ submitting, onSubmit }: TriggerPanelProps) {
  const [sourceText, setSourceText] = React.useState("");
  const [hooksText, setHooksText] = React.useState("");
  const [accountsText, setAccountsText] = React.useState("");
  const [subject, setSubject] = React.useState("");
  const [platforms, setPlatforms] = React.useState<PlatformOption[]>([]);

  const input = React.useMemo(
    () =>
      buildRunInput({
        sourceText,
        hooksText,
        accountsText,
        subject,
        platforms,
      }),
    [sourceText, hooksText, accountsText, subject, platforms],
  );
  const ready = canTriggerRun(input);
  const sourceCount = input.source_items?.length ?? 0;

  const togglePlatform = React.useCallback((platform: PlatformOption) => {
    setPlatforms((current) =>
      current.includes(platform)
        ? current.filter((p) => p !== platform)
        : [...current, platform],
    );
  }, []);

  const submit = React.useCallback(() => {
    if (!ready || submitting) return;
    onSubmit(input);
  }, [input, onSubmit, ready, submitting]);

  return (
    <View style={styles.panel}>
      <Text style={styles.heading}>Run this channel</Text>
      <Text style={styles.help}>
        One source per line (optional "title | body"). The runner expands, de-
        dupes and paces renders — publishing is scheduled separately.
      </Text>

      <TextInput
        style={styles.textarea}
        multiline
        autoCapitalize="sentences"
        placeholder={SOURCE_PLACEHOLDER}
        placeholderTextColor={colors.muted}
        value={sourceText}
        onChangeText={setSourceText}
        testID="source-input"
      />
      <Text style={styles.count}>
        {sourceCount} source{sourceCount === 1 ? "" : "s"}
      </Text>

      <TextInput
        style={styles.field}
        autoCapitalize="none"
        autoCorrect={false}
        placeholder="Subject (optional)"
        placeholderTextColor={colors.muted}
        value={subject}
        onChangeText={setSubject}
        testID="subject-input"
      />
      <TextInput
        style={styles.field}
        autoCapitalize="none"
        autoCorrect={false}
        placeholder="Hooks, comma-separated (optional)"
        placeholderTextColor={colors.muted}
        value={hooksText}
        onChangeText={setHooksText}
        testID="hooks-input"
      />
      <TextInput
        style={styles.field}
        autoCapitalize="none"
        autoCorrect={false}
        placeholder="Accounts, comma-separated (optional)"
        placeholderTextColor={colors.muted}
        value={accountsText}
        onChangeText={setAccountsText}
        testID="accounts-input"
      />

      <View style={styles.platforms}>
        {PLATFORM_OPTIONS.map((platform) => {
          const active = platforms.includes(platform);
          return (
            <Pressable
              key={platform}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => togglePlatform(platform)}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              testID={`platform-${platform}`}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>
                {platform}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <Pressable
        style={[styles.submit, (!ready || submitting) && styles.submitDisabled]}
        disabled={!ready || submitting}
        onPress={submit}
        accessibilityRole="button"
        accessibilityLabel="Trigger one render pass for this channel"
        testID="trigger-run-button"
      >
        {submitting ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.submitText}>Trigger run</Text>
        )}
      </Pressable>
    </View>
  );
}

export const TriggerPanel = React.memo(TriggerPanelBase);

const styles = StyleSheet.create({
  panel: { gap: 8 },
  heading: { color: colors.textPrimary, fontSize: 17, fontWeight: "700" },
  help: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  textarea: {
    minHeight: 96,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    color: colors.textPrimary,
    backgroundColor: colors.card,
    fontSize: 14,
    textAlignVertical: "top",
  },
  field: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.textPrimary,
    backgroundColor: colors.card,
    fontSize: 14,
  },
  count: { color: colors.muted, fontSize: 12 },
  platforms: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 4 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  chipTextActive: { color: "#fff" },
  submit: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 4,
    minHeight: 44,
    justifyContent: "center",
  },
  submitDisabled: { opacity: 0.5 },
  submitText: { color: "#fff", fontSize: 15, fontWeight: "700" },
});
