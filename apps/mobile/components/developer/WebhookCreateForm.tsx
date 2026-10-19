/**
 * Create-a-webhook-subscription form: an `https://` callback URL plus a
 * multi-select of the supported event types. On submit it calls the parent's
 * `onCreate`, which POSTs to the API — the callback URL is SSRF-validated
 * server-side (a private / loopback / metadata target is rejected as a 400) and
 * the signing secret is returned exactly once (surfaced by the parent). This form
 * holds no secret; it only collects the URL + event selection.
 */

import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";

interface WebhookCreateFormProps {
  /** The supported event catalog (from the API portal summary). */
  eventTypes: readonly string[];
  /** Create the subscription; resolves once the API responds (parent handles reveal). */
  onCreate: (url: string, eventTypes: string[]) => Promise<void>;
}

/** Loose client-side pre-check; the API is the real validator (incl. SSRF). */
function looksLikeHttpUrl(value: string): boolean {
  return /^https?:\/\/.+/i.test(value.trim());
}

export function WebhookCreateForm({
  eventTypes,
  onCreate,
}: WebhookCreateFormProps) {
  const [url, setUrl] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const toggle = useCallback((eventType: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(eventType)) next.delete(eventType);
      else next.add(eventType);
      return next;
    });
  }, []);

  const trimmedUrl = url.trim();
  const canSubmit = useMemo(
    () => !busy && looksLikeHttpUrl(trimmedUrl) && selected.size > 0,
    [busy, trimmedUrl, selected.size],
  );

  const submit = useCallback(async () => {
    if (busy) return;
    if (!looksLikeHttpUrl(trimmedUrl)) {
      setError("Enter a valid https:// callback URL.");
      return;
    }
    // Preserve the catalog order for the request.
    const chosen = eventTypes.filter((e) => selected.has(e));
    if (chosen.length === 0) {
      setError("Select at least one event type.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onCreate(trimmedUrl, chosen);
      // Reset on success (the parent surfaces the one-time secret).
      setUrl("");
      setSelected(new Set());
    } catch (err) {
      setError(describeError(err, "Couldn’t create the subscription."));
    } finally {
      setBusy(false);
    }
  }, [busy, trimmedUrl, eventTypes, selected, onCreate]);

  return (
    <View style={styles.card}>
      <Text style={styles.label}>Callback URL</Text>
      <TextInput
        style={styles.input}
        value={url}
        onChangeText={setUrl}
        placeholder="https://example.com/webhooks/menivor"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        editable={!busy}
        accessibilityLabel="Webhook callback URL"
      />

      <Text style={styles.label}>Events</Text>
      <View style={styles.chips}>
        {eventTypes.map((eventType) => {
          const on = selected.has(eventType);
          return (
            <Pressable
              key={eventType}
              onPress={() => toggle(eventType)}
              disabled={busy}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: on }}
              accessibilityLabel={eventType}
              style={[styles.chip, on && styles.chipOn]}
            >
              <Text style={[styles.chipText, on && styles.chipTextOn]}>
                {eventType}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <Pressable
        style={[styles.submit, !canSubmit && styles.submitDisabled]}
        onPress={submit}
        disabled={!canSubmit}
        accessibilityRole="button"
        accessibilityLabel="Create webhook subscription"
      >
        {busy ? (
          <ActivityIndicator color={colors.textPrimary} />
        ) : (
          <Text style={styles.submitText}>Create subscription</Text>
        )}
      </Pressable>
      <Text style={styles.hint}>
        The signing secret is shown once, right after you create it. Internal or
        private URLs are rejected by the server.
      </Text>
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
  label: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.6,
  },
  input: {
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 14,
  },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 7,
    backgroundColor: colors.cardAlt,
  },
  chipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary, fontSize: 12, fontWeight: "600" },
  chipTextOn: { color: colors.textPrimary },
  error: { color: colors.error, fontSize: 13 },
  submit: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 2,
  },
  submitDisabled: { opacity: 0.5 },
  submitText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
  hint: { color: colors.muted, fontSize: 12, lineHeight: 17 },
});
