/**
 * One-time reveal of a freshly created webhook subscription's HMAC signing
 * secret. SECURITY: this is the ONLY place the plaintext secret is ever shown —
 * the server keeps only a Fernet-encrypted blob, so once this banner is dismissed
 * the value is unrecoverable (a lost secret means the subscription must be
 * re-created). It renders the secret with a Copy button (RN's built-in
 * `Clipboard`, no extra dependency) and a clear warning, then a Done button that
 * clears it from screen (and from memory in the parent). The value is never
 * persisted anywhere. Mirrors the API-keys {@link RevealedKeyBanner} pattern.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Clipboard, Pressable, StyleSheet, Text, View } from "react-native";

import type { CreatedWebhookSubscription } from "@/lib/developer";

import { colors } from "@/components/me/theme";

interface RevealedSecretBannerProps {
  subscription: CreatedWebhookSubscription;
  /** Dismiss the banner (the raw secret is dropped from memory by the parent). */
  onDismiss: () => void;
}

const COPIED_RESET_MS = 1500;

export function RevealedSecretBanner({
  subscription,
  onDismiss,
}: RevealedSecretBannerProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const onCopy = useCallback(() => {
    if (!subscription.secret) return;
    Clipboard.setString(subscription.secret);
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), COPIED_RESET_MS);
  }, [subscription.secret]);

  return (
    <View style={styles.card}>
      <Text style={styles.title}>Signing secret</Text>
      <Text style={styles.warning}>
        Copy it now — this is the only time it will be shown. We store only an
        encrypted copy, so it can’t be recovered later. Use it to verify the{" "}
        <Text style={styles.code}>webhook-signature</Text> header on each
        delivery (Standard Webhooks; the body-only{" "}
        <Text style={styles.code}>X-Menivor-Signature</Text> is still sent but
        deprecated).
      </Text>

      <View style={styles.secretBox}>
        <Text style={styles.secretText} selectable numberOfLines={3}>
          {subscription.secret}
        </Text>
      </View>

      <Text style={styles.meta} numberOfLines={1}>
        {subscription.url}
      </Text>

      <View style={styles.actions}>
        <Pressable
          style={styles.copy}
          onPress={onCopy}
          accessibilityRole="button"
          accessibilityLabel="Copy signing secret"
        >
          <Text style={styles.copyText}>
            {copied ? "Copied" : "Copy secret"}
          </Text>
        </Pressable>
        <Pressable
          style={styles.done}
          onPress={onDismiss}
          accessibilityRole="button"
          accessibilityLabel="Dismiss signing secret"
        >
          <Text style={styles.doneText}>Done</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
  },
  title: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  warning: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  code: { color: colors.accent, fontFamily: "monospace", fontSize: 12 },
  secretBox: {
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
  },
  secretText: {
    color: colors.textPrimary,
    fontSize: 13,
    fontFamily: "monospace",
    lineHeight: 19,
  },
  meta: { color: colors.muted, fontSize: 12 },
  actions: { flexDirection: "row", gap: 10 },
  copy: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  copyText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
  done: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    paddingHorizontal: 18,
    alignItems: "center",
    justifyContent: "center",
  },
  doneText: { color: colors.textSecondary, fontWeight: "600", fontSize: 15 },
});
