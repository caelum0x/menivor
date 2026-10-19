/**
 * Draft Social Copy — generate a platform-tailored post title, caption and
 * hashtags from a free-form subject you type in, BEFORE any reel exists. This
 * is the planning counterpart to AI Social Copy (which needs a finished reel):
 * sketch a hook, pick a platform, and get ready-to-paste copy you can iterate
 * on, then carry into rendering.
 *
 * Pipeline:
 *   GET  /catalog/social-platforms → the platforms the generator supports
 *   POST /social-metadata          → { title, caption, hashtags[] }
 *
 * NAV MANIFEST (for the integration agent):
 *   { route: "/connections/social-metadata", title: "Draft Social Copy" }
 *
 * Accepts optional deep-link params `?subject=` and `?platform=` to prefill.
 */

import * as React from "react";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { generateSocialMetadata, listSocialPlatforms } from "@/lib/api";
import {
  SOCIAL_METADATA_SCRIPT_MAX,
  SOCIAL_METADATA_SUBJECT_MAX,
} from "@/lib/types";
import type {
  SocialMeta,
  SocialMetadataRequest,
  SocialPlatform,
} from "@/lib/types";

import { CopyableField } from "@/components/social/CopyableField";
import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";

/** Validation outcome for the subject field. */
interface FieldError {
  subject?: string;
}

/** Trim + validate the required subject; returns a user-facing message or null. */
function validateSubject(subject: string): string | null {
  const trimmed = subject.trim();
  if (trimmed.length === 0) return "Enter a subject to write copy about.";
  if (trimmed.length > SOCIAL_METADATA_SUBJECT_MAX) {
    return `Keep the subject under ${SOCIAL_METADATA_SUBJECT_MAX} characters.`;
  }
  return null;
}

export default function SocialMetadataScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ subject?: string; platform?: string }>();

  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);
  const [loadError, setLoadError] = React.useState("");
  const [platforms, setPlatforms] = React.useState<SocialPlatform[]>([]);

  const [subject, setSubject] = React.useState("");
  const [script, setScript] = React.useState("");
  const [language, setLanguage] = React.useState("");
  const [platform, setPlatform] = React.useState<string | null>(null);

  const [fieldError, setFieldError] = React.useState<FieldError>({});
  const [generating, setGenerating] = React.useState(false);
  const [genError, setGenError] = React.useState("");
  const [meta, setMeta] = React.useState<SocialMeta | null>(null);

  const applyPrefill = React.useCallback(
    (next: SocialPlatform[]) => {
      const preferredPlatform = String(params.platform ?? "");
      setPlatform((current) => {
        if (
          preferredPlatform &&
          next.some((p) => String(p.id) === preferredPlatform)
        ) {
          return preferredPlatform;
        }
        if (current && next.some((p) => String(p.id) === current)) {
          return current;
        }
        return next[0] ? String(next[0].id) : null;
      });
      setSubject((current) => {
        const preferred = String(params.subject ?? "").trim();
        return current.length === 0 && preferred ? preferred : current;
      });
    },
    [params.platform, params.subject],
  );

  const runLoad = React.useCallback(async () => {
    setLoadError("");
    try {
      const plats = await listSocialPlatforms({ token });
      setPlatforms(plats);
      applyPrefill(plats);
    } catch (err) {
      setLoadError(describeError(err, "Failed to load platforms."));
    }
  }, [token, applyPrefill]);

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    void (async () => {
      await runLoad();
      if (active) setLoading(false);
    })();
    return () => {
      active = false;
    };
  }, [runLoad]);

  const onRefresh = React.useCallback(async () => {
    setRefreshing(true);
    await runLoad();
    setRefreshing(false);
  }, [runLoad]);

  const onGenerate = React.useCallback(async () => {
    const subjectError = validateSubject(subject);
    if (subjectError) {
      setFieldError({ subject: subjectError });
      return;
    }
    setFieldError({});
    if (!platform) {
      setGenError("Pick a platform to tailor the copy for.");
      return;
    }
    setGenerating(true);
    setGenError("");
    setMeta(null);
    try {
      const trimmedScript = script.trim();
      const trimmedLang = language.trim();
      const body: SocialMetadataRequest = {
        video_subject: subject.trim(),
        platform,
        ...(trimmedScript ? { video_script: trimmedScript } : {}),
        ...(trimmedLang ? { language: trimmedLang } : {}),
      };
      const res = await generateSocialMetadata(body, { token });
      setMeta(res);
    } catch (err) {
      setGenError(describeError(err, "Failed to generate copy."));
    } finally {
      setGenerating(false);
    }
  }, [subject, script, language, platform, token]);

  const subjectRemaining = SOCIAL_METADATA_SUBJECT_MAX - subject.trim().length;
  const scriptRemaining = SOCIAL_METADATA_SCRIPT_MAX - script.trim().length;
  const scriptTooLong = scriptRemaining < 0;
  const canGenerate =
    subject.trim().length > 0 && !!platform && !scriptTooLong && !generating;
  const hashtagsDisplay = meta?.hashtags?.length
    ? meta.hashtags.join(" ")
    : "";

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => void onRefresh()}
          tintColor={colors.accent}
        />
      }
    >
      <Stack.Screen options={{ title: "Draft Social Copy" }} />

      <Text style={styles.intro}>
        Sketch a post before you render. Type what the reel is about, pick a
        platform, and get a ready-to-paste title, caption and hashtags you can
        iterate on.
      </Text>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.muted}>Loading platforms…</Text>
        </View>
      ) : loadError ? (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{loadError}</Text>
          <Pressable
            style={styles.retry}
            onPress={() => void onRefresh()}
            accessibilityRole="button"
          >
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.form}>
          <Text style={styles.fieldLabel}>SUBJECT</Text>
          <TextInput
            style={[styles.input, fieldError.subject ? styles.inputError : null]}
            value={subject}
            onChangeText={(t) => {
              setSubject(t);
              if (fieldError.subject) setFieldError({});
            }}
            placeholder="e.g. 3 morning habits that changed my focus"
            placeholderTextColor={colors.muted}
            multiline
            editable={!generating}
            accessibilityLabel="Post subject"
          />
          <View style={styles.metaRow}>
            {fieldError.subject ? (
              <Text style={styles.error}>{fieldError.subject}</Text>
            ) : (
              <Text style={styles.muted}>Required</Text>
            )}
            <Text
              style={[styles.counter, subjectRemaining < 0 && styles.counterOver]}
            >
              {subjectRemaining}
            </Text>
          </View>

          <Text style={styles.fieldLabel}>SCRIPT / NOTES (OPTIONAL)</Text>
          <TextInput
            style={[
              styles.input,
              styles.inputTall,
              scriptTooLong ? styles.inputError : null,
            ]}
            value={script}
            onChangeText={setScript}
            placeholder="Add talking points or a rough script for richer copy."
            placeholderTextColor={colors.muted}
            multiline
            editable={!generating}
            accessibilityLabel="Post script or notes"
          />
          <View style={styles.metaRow}>
            <Text style={styles.muted}>
              {scriptTooLong ? "Too long — trim it down." : "Optional"}
            </Text>
            <Text
              style={[styles.counter, scriptTooLong && styles.counterOver]}
            >
              {scriptRemaining}
            </Text>
          </View>

          <Text style={styles.fieldLabel}>PLATFORM</Text>
          {platforms.length === 0 ? (
            <Text style={styles.muted}>
              No platforms available right now — pull to refresh.
            </Text>
          ) : (
            <View style={styles.chips}>
              {platforms.map((p) => {
                const id = String(p.id);
                const selected = id === platform;
                return (
                  <Pressable
                    key={id}
                    style={[styles.chip, selected && styles.chipOn]}
                    onPress={() => setPlatform(id)}
                    accessibilityRole="button"
                    accessibilityState={{ selected }}
                  >
                    <Text
                      style={[styles.chipText, selected && styles.chipTextOn]}
                    >
                      {p.name || id}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          )}

          <Text style={styles.fieldLabel}>LANGUAGE (OPTIONAL)</Text>
          <TextInput
            style={styles.input}
            value={language}
            onChangeText={setLanguage}
            placeholder="e.g. en, es, tr — leave blank to auto-detect"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            autoCorrect={false}
            editable={!generating}
            accessibilityLabel="Output language"
          />

          {genError ? <Text style={styles.error}>{genError}</Text> : null}

          <Pressable
            style={[styles.generate, !canGenerate && styles.generateDisabled]}
            onPress={() => void onGenerate()}
            disabled={!canGenerate}
            accessibilityRole="button"
            accessibilityLabel="Generate draft social copy"
            accessibilityState={{ disabled: !canGenerate }}
          >
            {generating ? (
              <ActivityIndicator color={colors.bg} size="small" />
            ) : (
              <Text style={styles.generateText}>
                {meta ? "Regenerate copy" : "Generate copy"}
              </Text>
            )}
          </Pressable>

          {meta ? (
            <View style={styles.result}>
              <CopyableField
                label="Title"
                value={meta.title ?? ""}
                emptyText="No title generated"
              />
              <CopyableField
                label="Caption"
                value={meta.caption ?? ""}
                emptyText="No caption generated"
              />
              <CopyableField
                label="Hashtags"
                value={hashtagsDisplay}
                emptyText="No hashtags generated"
              />
            </View>
          ) : null}
        </View>
      )}

      <Pressable
        style={styles.manageLink}
        onPress={() => router.push("/connections/social-copy")}
        accessibilityRole="link"
      >
        <Text style={styles.manageLinkText}>
          Have a finished reel? Write copy from it
        </Text>
      </Pressable>
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, gap: 12 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  center: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 28,
    gap: 8,
  },
  muted: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  errorBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
    alignItems: "flex-start",
  },
  errorText: { color: colors.error, fontSize: 14 },
  retry: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  retryText: { color: colors.textSecondary, fontWeight: "600" },
  form: { gap: 10 },
  fieldLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.5,
    marginTop: 4,
  },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
    backgroundColor: colors.card,
    maxWidth: "100%",
  },
  chipOn: { borderColor: colors.primary, backgroundColor: colors.cardAlt },
  chipText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  chipTextOn: { color: colors.accent },
  input: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    color: colors.textPrimary,
    fontSize: 14,
    backgroundColor: colors.card,
  },
  inputTall: { minHeight: 96, textAlignVertical: "top" },
  inputError: { borderColor: colors.error },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  counter: { color: colors.muted, fontSize: 12 },
  counterOver: { color: colors.error, fontWeight: "700" },
  generate: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 4,
  },
  generateDisabled: { opacity: 0.5 },
  generateText: { color: colors.bg, fontWeight: "700", fontSize: 15 },
  result: {
    gap: 10,
    marginTop: 8,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    paddingTop: 12,
  },
  error: { color: colors.error, fontSize: 13, flexShrink: 1 },
  manageLink: { alignSelf: "flex-start", paddingVertical: 10 },
  manageLinkText: { color: colors.accent, fontSize: 13, fontWeight: "600" },
  spacer: { height: 24 },
});
