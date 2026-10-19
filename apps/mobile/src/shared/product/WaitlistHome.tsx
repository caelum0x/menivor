import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";
import {
  pickRecordingFromFiles,
  pickRecordingFromLibrary,
} from "@/src/shared/media";
import { listCaptionStyles } from "@/lib/api";
import type { CaptionStyle } from "@/lib/types";
import type { LocalFile } from "@/lib/api";

import { assColorToCss } from "@/src/features/reel-create/components/caption-colors";
import { persistDraftMedia } from "./draft-media";
import { saveDraft } from "./drafts";
import {
  WAITLIST_FALLBACK_EMAIL,
  submitWaitlist,
  waitlistUrl,
  type WaitlistOutcome,
} from "./waitlist";

interface WaitlistHomeProps {
  /** Session API key, used only for the best-effort caption preview fetch. */
  readonly token?: string;
  /** Attribution tag stored with the signup. */
  readonly source?: string;
}

type FormStatus = "idle" | "submitting" | "success" | "unavailable" | "error";

/**
 * The honest waitlist-era home. Rendered wherever reel generation is not yet
 * available (the standalone /waitlist route reached from a fail-open sign-in,
 * and the Create tab when the backend reports generation off). It never dead
 * ends: a creator can join the live waitlist, preview the product's own caption
 * looks, and record/import a clip now to have it ready when generation lights
 * up. No data is fabricated — the caption preview only shows styles the live
 * catalog returns, and a signup is only "on the list" when the server confirms.
 */
export function WaitlistHome({ token, source = "mobile-waitlist" }: WaitlistHomeProps) {
  const router = useRouter();

  // --- Waitlist signup ----------------------------------------------------
  const [email, setEmail] = useState("");
  const [honeypot, setHoneypot] = useState("");
  const [formStatus, setFormStatus] = useState<FormStatus>("idle");
  const [formError, setFormError] = useState("");

  const onJoin = async () => {
    if (formStatus === "submitting") return;
    setFormStatus("submitting");
    setFormError("");
    const outcome: WaitlistOutcome = await submitWaitlist(email, source, {
      honeypot,
    });
    switch (outcome.status) {
      case "ok":
        setFormStatus("success");
        setEmail("");
        return;
      case "unavailable":
        setFormStatus("unavailable");
        return;
      case "invalid":
        setFormStatus("error");
        setFormError(outcome.message);
        return;
      case "error":
        setFormStatus("error");
        setFormError(outcome.message);
    }
  };

  // --- Record / import for later -----------------------------------------
  const [subject, setSubject] = useState("");
  const [clip, setClip] = useState<LocalFile | null>(null);
  const [savedDraftId, setSavedDraftId] = useState<string | null>(null);
  const [draftError, setDraftError] = useState("");

  const pickClip = async (from: "library" | "files") => {
    setDraftError("");
    try {
      const picked =
        from === "library"
          ? await pickRecordingFromLibrary()
          : await pickRecordingFromFiles();
      if (picked) {
        setClip(picked);
        setSavedDraftId(null);
      }
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : "Could not pick a clip.");
    }
  };

  const canSaveDraft = subject.trim().length > 0 || clip !== null;

  const onSaveDraft = async () => {
    if (!canSaveDraft) return;
    setDraftError("");
    try {
      // Copy the clip out of the picker cache first so the OS cannot purge it
      // before the creator comes back to this draft.
      const media = clip
        ? await persistDraftMedia({
            uri: clip.uri,
            name: clip.name,
            mimeType: clip.mimeType,
            size: clip.size,
          })
        : undefined;
      const draft = await saveDraft({
        subject: subject.trim(),
        ...(media ? { media } : {}),
      });
      setSavedDraftId(draft.id);
      setSubject("");
      setClip(null);
    } catch {
      setDraftError("Could not save your draft. Please try again.");
    }
  };

  // --- Caption preview (best effort) -------------------------------------
  const [styles_, setStyles] = useState<CaptionStyle[]>([]);
  const [stylesState, setStylesState] = useState<"loading" | "ready" | "empty">(
    "loading",
  );

  useEffect(() => {
    let active = true;
    setStylesState("loading");
    listCaptionStyles({ token })
      .then((list) => {
        if (!active) return;
        setStyles(list);
        setStylesState(list.length > 0 ? "ready" : "empty");
      })
      .catch(() => {
        if (active) setStylesState("empty");
      });
    return () => {
      active = false;
    };
  }, [token]);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.kicker}>01 / EARLY ACCESS</Text>
      <Text style={styles.title}>Reel generation is opening in waves.</Text>
      <Text style={styles.lead}>
        Menivor turns a screen recording into a vertical, captioned UGC reel.
        Generation isn&rsquo;t switched on for your account yet — join the
        waitlist and get set up so you&rsquo;re ready the moment it is.
      </Text>

      {/* Join the waitlist */}
      <View style={styles.card}>
        <Text style={styles.kickerAccent}>02 / WAITLIST</Text>
        <Text style={styles.cardTitle}>Join the waitlist</Text>
        {formStatus === "success" ? (
          <Text style={styles.success}>
            You&rsquo;re on the list — we&rsquo;ll email you when your spot opens.
          </Text>
        ) : formStatus === "unavailable" ? (
          <Text style={styles.muted}>
            Signups are paused right now. Email{" "}
            <Text
              style={styles.linkInline}
              onPress={() =>
                void Linking.openURL(
                  `mailto:${WAITLIST_FALLBACK_EMAIL}?subject=Menivor%20waitlist`,
                )
              }
            >
              {WAITLIST_FALLBACK_EMAIL}
            </Text>{" "}
            and we&rsquo;ll add you by hand.
          </Text>
        ) : (
          <>
            <TextInput
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              placeholder="you@company.com"
              placeholderTextColor={colors.textFaint}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="email"
              editable={formStatus !== "submitting"}
            />
            {/* Honeypot — offscreen; humans never see it, bots fill it. */}
            <TextInput
              style={styles.honeypot}
              value={honeypot}
              onChangeText={setHoneypot}
              autoCapitalize="none"
              autoCorrect={false}
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
            />
            {formStatus === "error" ? (
              <Text style={styles.error}>{formError}</Text>
            ) : null}
            <Pressable
              style={styles.primary}
              onPress={() => void onJoin()}
              disabled={formStatus === "submitting"}
              accessibilityRole="button"
            >
              {formStatus === "submitting" ? (
                <ActivityIndicator color={colors.onAccent} />
              ) : (
                <Text style={styles.primaryText}>Join the waitlist</Text>
              )}
            </Pressable>
          </>
        )}
      </View>

      {/* Record / import for later */}
      <View style={styles.card}>
        <Text style={styles.kickerAccent}>03 / RECORD</Text>
        <Text style={styles.cardTitle}>Record a clip for later</Text>
        <Text style={styles.muted}>
          Import a screen recording and note what it&rsquo;s about. We save it on
          this device as a draft — ready to turn into a reel the moment
          generation opens for you.
        </Text>

        <TextInput
          style={styles.input}
          value={subject}
          onChangeText={setSubject}
          placeholder="What is this reel about?"
          placeholderTextColor={colors.textFaint}
          multiline
        />

        <View style={styles.row}>
          <Pressable
            style={styles.secondary}
            onPress={() => void pickClip("library")}
          >
            <Text style={styles.secondaryText}>From library</Text>
          </Pressable>
          <Pressable
            style={styles.secondary}
            onPress={() => void pickClip("files")}
          >
            <Text style={styles.secondaryText}>Browse files</Text>
          </Pressable>
        </View>

        {clip ? (
          <Text style={styles.muted} numberOfLines={1}>
            Attached: {clip.name} · {(clip.size / (1024 * 1024)).toFixed(1)} MB
          </Text>
        ) : null}

        {draftError ? <Text style={styles.error}>{draftError}</Text> : null}

        <Pressable
          style={[styles.primary, !canSaveDraft && styles.disabled]}
          onPress={() => void onSaveDraft()}
          disabled={!canSaveDraft}
          accessibilityRole="button"
        >
          <Text style={styles.primaryText}>Save draft</Text>
        </Pressable>

        {savedDraftId ? (
          <Pressable
            onPress={() => router.push("/drafts")}
            accessibilityRole="link"
          >
            <Text style={styles.success}>
              Saved to Drafts. Tap to view your drafts.
            </Text>
          </Pressable>
        ) : null}
      </View>

      {/* Caption preview */}
      <View style={styles.card}>
        <Text style={styles.kickerAccent}>04 / LOOK</Text>
        <Text style={styles.cardTitle}>Caption styles</Text>
        {stylesState === "loading" ? (
          <ActivityIndicator color={colors.accent} />
        ) : stylesState === "empty" ? (
          <Text style={styles.muted}>
            Caption previews load once you&rsquo;re connected. The signature look
            is bold word-by-word captions in Menivor yellow.
          </Text>
        ) : (
          <View style={styles.styleList}>
            {styles_.map((style) => (
              <View key={style.id} style={styles.styleRow}>
                <View
                  style={[
                    styles.swatch,
                    { backgroundColor: assColorToCss(style.primary, colors.accent) },
                  ]}
                />
                <View style={styles.styleMeta}>
                  <Text style={styles.styleName}>{style.name}</Text>
                  {style.description ? (
                    <Text style={styles.muted} numberOfLines={2}>
                      {style.description}
                    </Text>
                  ) : null}
                </View>
              </View>
            ))}
          </View>
        )}
      </View>

      <Text style={styles.endpoint}>Waitlist endpoint: {waitlistUrl()}</Text>
      <View style={{ height: spacing.xxl }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.xl, gap: spacing.md },
  kicker: { ...kicker },
  kickerAccent: { ...kicker, color: colors.accent },
  title: {
    color: colors.textPrimary,
    fontSize: typeScale.title,
    fontWeight: "800",
    letterSpacing: -0.5,
    lineHeight: 32,
  },
  lead: {
    color: colors.textSecondary,
    fontSize: typeScale.body,
    lineHeight: 22,
  },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  cardTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.heading,
    fontWeight: "700",
  },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  input: {
    backgroundColor: colors.input,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    color: colors.textPrimary,
    fontSize: typeScale.body,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    minHeight: 48,
    textAlignVertical: "top",
  },
  honeypot: { height: 0, width: 0, opacity: 0 },
  row: { flexDirection: "row", gap: spacing.sm },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 48,
  },
  primaryText: { color: colors.onAccent, fontSize: typeScale.body, fontWeight: "700" },
  disabled: { opacity: 0.4 },
  secondary: {
    flex: 1,
    backgroundColor: colors.surfaceAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: "center",
  },
  secondaryText: { color: colors.textPrimary, fontWeight: "600" },
  success: { color: colors.accent, fontSize: typeScale.caption, fontWeight: "600", lineHeight: 19 },
  error: { color: colors.danger, fontSize: typeScale.caption },
  linkInline: {
    color: colors.accent,
    textDecorationLine: "underline",
    fontWeight: "600",
  },
  styleList: { gap: spacing.sm, marginTop: spacing.xs },
  styleRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  swatch: {
    width: 28,
    height: 28,
    borderRadius: radius.sm,
    borderColor: colors.border,
    borderWidth: 1,
  },
  styleMeta: { flex: 1, gap: 2 },
  styleName: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600" },
  endpoint: {
    color: colors.textFaint,
    fontSize: typeScale.micro,
    textAlign: "center",
    marginTop: spacing.sm,
  },
});
