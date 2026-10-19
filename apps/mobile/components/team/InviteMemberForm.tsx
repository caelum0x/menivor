/**
 * Invite-by-email form. Collects an email and a role, then hands the request to
 * the parent: an existing account is added straight to the members list; an
 * email without an account becomes a pending invite with a shareable join link.
 * Owns its own submitting/error state and only renders for callers allowed to
 * manage members.
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

import type { InviteMemberRequest, WorkspaceRole } from "@/lib/types";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";

import { RolePicker } from "./RolePicker";

interface InviteMemberFormProps {
  /** Performs the invite; resolves once the new member is in the list. */
  onInvite: (body: InviteMemberRequest) => Promise<void>;
}

/** Minimal email shape check — the backend is the source of truth. */
function isLikelyEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export function InviteMemberForm({ onInvite }: InviteMemberFormProps) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WorkspaceRole>("member");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = !!email.trim() && !submitting;

  const onSubmit = async () => {
    const trimmed = email.trim();
    if (!isLikelyEmail(trimmed)) {
      setError("Enter a valid email address.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onInvite({ email: trimmed, role });
      setEmail("");
      setRole("member");
    } catch (err) {
      setError(describeError(err, "Failed to invite member."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.label}>Invite by email</Text>
      <TextInput
        style={styles.input}
        value={email}
        onChangeText={(text) => {
          setEmail(text);
          if (error) setError(null);
        }}
        placeholder="teammate@example.com"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        spellCheck={false}
        editable={!submitting}
      />
      <Text style={styles.subLabel}>Role</Text>
      <RolePicker selected={role} onSelect={setRole} disabled={submitting} />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        style={[styles.button, !canSubmit && styles.buttonDisabled]}
        onPress={onSubmit}
        disabled={!canSubmit}
        accessibilityRole="button"
        accessibilityLabel="Send invite"
        accessibilityState={{ disabled: !canSubmit }}
      >
        {submitting ? (
          <ActivityIndicator color={colors.textPrimary} />
        ) : (
          <Text style={styles.buttonText}>Send invite</Text>
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
