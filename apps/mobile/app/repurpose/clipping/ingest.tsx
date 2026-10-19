/**
 * Route: /repurpose/clipping/ingest — turn a web URL into a reel draft.
 *
 * NAV MANIFEST:
 *   { route: "/repurpose/clipping/ingest", title: "Import from URL" }
 *
 * Paste a product/article URL; the backend fetches + extracts it and returns a
 * hook-first reel draft (POST /ingest/url) which is previewed here, ready to be
 * submitted to the reel pipeline. Client-side URL validation, plus loading /
 * error / result states. No job is created by this screen.
 *
 * Auth flows through the shared api client (x-api-key). No secrets here.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Stack } from "expo-router";

import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, radius, spacing, typeScale, weight } from "@/src/shared/theme";
import { ingestUrl, looksLikeUrl, type IngestResult } from "@/lib/repurpose";

import { ReelDraftCard } from "@/src/features/repurpose/components/ReelDraftCard";

export default function IngestUrlScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResult | null>(null);

  const trimmed = url.trim();
  const valid = looksLikeUrl(trimmed);
  const canSubmit = valid && !busy;

  const onSubmit = useCallback(async () => {
    const target = url.trim();
    if (!looksLikeUrl(target)) {
      setError("Enter a valid http(s) URL.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const ingested = await ingestUrl(target, { token });
      setResult(ingested);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not import that URL.",
      );
    } finally {
      setBusy(false);
    }
  }, [url, token]);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Stack.Screen options={{ title: "Import from URL" }} />

      <Text style={styles.intro}>
        Paste a product page or article URL. We extract the key points and draft
        a hook-first reel you can submit to the pipeline.
      </Text>

      <Text style={styles.label}>Page URL</Text>
      <TextInput
        style={styles.input}
        value={url}
        onChangeText={setUrl}
        placeholder="https://example.com/product"
        placeholderTextColor={colors.textFaint}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        editable={!busy}
      />
      {trimmed.length > 0 && !valid ? (
        <Text style={styles.warn}>That does not look like an http(s) URL.</Text>
      ) : null}

      <Pressable
        style={[styles.submit, !canSubmit && styles.submitDim]}
        onPress={onSubmit}
        disabled={!canSubmit}
        accessibilityRole="button"
        accessibilityLabel="Import this URL into a reel draft"
        accessibilityState={{ busy, disabled: !canSubmit }}
      >
        {busy ? (
          <ActivityIndicator color={colors.onAccent} />
        ) : (
          <Text style={styles.submitText}>Import & draft</Text>
        )}
      </Pressable>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {result ? (
        <View style={styles.resultBlock}>
          {result.content.title ? (
            <>
              <Text style={styles.extractLabel}>EXTRACTED</Text>
              <Text style={styles.extractTitle}>{result.content.title}</Text>
              {result.content.description ? (
                <Text style={styles.extractBody} numberOfLines={4}>
                  {result.content.description}
                </Text>
              ) : null}
            </>
          ) : null}
          <ReelDraftCard draft={result.reel_draft} />
          <Text style={styles.hint}>
            Head to Create to submit this draft to the reel pipeline.
          </Text>
        </View>
      ) : null}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.sm },
  intro: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 20,
    marginBottom: spacing.sm,
  },
  label: {
    color: colors.textPrimary,
    fontSize: typeScale.caption,
    fontWeight: weight.semibold,
    marginBottom: spacing.xs,
  },
  input: {
    backgroundColor: colors.input,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    color: colors.textPrimary,
    fontSize: typeScale.body,
  },
  warn: { color: colors.danger, fontSize: typeScale.micro, marginTop: spacing.xs },
  submit: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 48,
    marginTop: spacing.md,
  },
  submitDim: { opacity: 0.45 },
  submitText: {
    color: colors.onAccent,
    fontSize: typeScale.body,
    fontWeight: weight.bold,
  },
  error: { color: colors.danger, fontSize: typeScale.caption, lineHeight: 18 },
  resultBlock: { gap: spacing.sm, marginTop: spacing.md },
  extractLabel: {
    color: colors.textFaint,
    fontSize: typeScale.micro,
    fontWeight: weight.bold,
    letterSpacing: 1,
  },
  extractTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.bold,
  },
  extractBody: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 19,
  },
  hint: {
    color: colors.textFaint,
    fontSize: typeScale.micro,
    lineHeight: 16,
  },
  spacer: { height: 48 },
});
