import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useRouter } from "expo-router";

import {
  BETA_EMAIL_MAX,
  BETA_USE_CASE_MAX,
  FORMAT_DETAIL,
  checkBetaFields,
  getBetaLaunchStatus,
  submitBetaRequest,
  type BetaLaunchStatus,
  type LaunchFormat,
} from "@/lib/beta";
import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";

type FormStatus = "idle" | "submitting" | "received" | "error";

/**
 * Private-beta access request. Posts email + use case to POST /beta/request
 * and shows the server's neutral confirmation (it never says whether an email
 * was already listed). Lists the keyless formats the server reports as live
 * right now. Approved emails go back to sign-in and continue normally.
 */
export default function BetaRequestScreen() {
  const router = useRouter();
  const [launch, setLaunch] = useState<BetaLaunchStatus | null>(null);
  const [launchState, setLaunchState] = useState<"loading" | "ready" | "failed">("loading");
  const [email, setEmail] = useState("");
  const [useCase, setUseCase] = useState("");
  const [status, setStatus] = useState<FormStatus>("idle");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getBetaLaunchStatus({ signal: controller.signal })
      .then((next) => {
        setLaunch(next);
        setLaunchState("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setLaunchState("failed");
      });
    return () => controller.abort();
  }, []);

  const backToSignIn = () => {
    if (router.canGoBack()) router.back();
    else router.replace("/");
  };

  const onSubmit = async () => {
    if (status === "submitting") return;
    const check = checkBetaFields(email, useCase);
    if (!check.ok) {
      setStatus("error");
      setMessage(check.error);
      return;
    }
    setStatus("submitting");
    setMessage("");
    const outcome = await submitBetaRequest(check.email, check.useCase, "mobile-beta");
    setMessage(outcome.message);
    if (outcome.status === "received") {
      setStatus("received");
      setEmail("");
      setUseCase("");
    } else {
      setStatus("error");
    }
  };

  const submitting = status === "submitting";

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.kicker}>PRIVATE BETA</Text>
        <Text style={styles.title}>Request early access</Text>

        {launch?.phase === "public" ? (
          <View style={styles.card}>
            <Text style={styles.body}>
              Menivor is open to everyone now, no request needed.
            </Text>
            <Pressable style={styles.primary} onPress={backToSignIn} accessibilityRole="button">
              <Text style={styles.primaryText}>Start creating</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <Text style={styles.body}>
              Menivor is open to a small group while render capacity comes online. We
              approve requests by hand; once your email is approved, sign in with it
              and continue normally.
            </Text>

            <View style={styles.card}>
              {status === "received" ? (
                <>
                  <Text style={styles.success}>{message}</Text>
                  <Text style={styles.muted}>
                    Approval is manual and not instant. Once approved, sign in with the same email.
                  </Text>
                </>
              ) : (
                <>
                  <Text style={styles.label}>Email</Text>
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
                    maxLength={BETA_EMAIL_MAX}
                    editable={!submitting}
                  />
                  <Text style={styles.label}>What do you want to make?</Text>
                  <TextInput
                    style={[styles.input, styles.multiline]}
                    value={useCase}
                    onChangeText={setUseCase}
                    placeholder="For example: captioned product demos for TikTok, 3 a week"
                    placeholderTextColor={colors.textFaint}
                    multiline
                    maxLength={BETA_USE_CASE_MAX}
                    editable={!submitting}
                  />
                  {status === "error" && message ? (
                    <Text style={styles.error} accessibilityRole="alert">
                      {message}
                    </Text>
                  ) : null}
                  <Pressable
                    style={[styles.primary, submitting && styles.busy]}
                    onPress={() => void onSubmit()}
                    disabled={submitting}
                    accessibilityRole="button"
                  >
                    {submitting ? (
                      <ActivityIndicator color={colors.onAccent} />
                    ) : (
                      <Text style={styles.primaryText}>Request early access</Text>
                    )}
                  </Pressable>
                  <Text style={styles.muted}>
                    Free during the beta. We only use your email to reply about access.
                  </Text>
                </>
              )}
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>Available in the beta now</Text>
              {launchState === "loading" ? (
                <ActivityIndicator color={colors.accent} />
              ) : launchState === "failed" ? (
                <Text style={styles.muted}>
                  Could not load which formats are live. Your request still goes through.
                </Text>
              ) : launch && launch.availableFormats.length > 0 ? (
                launch.availableFormats.map((format: LaunchFormat) => (
                  <View key={format.id} style={styles.format}>
                    <Text style={styles.formatTitle}>{format.label}</Text>
                    <Text style={styles.muted}>{FORMAT_DETAIL[format.id] ?? format.notes}</Text>
                  </View>
                ))
              ) : (
                <Text style={styles.muted}>
                  No format is rendering on the beta servers yet. Approved requests get an
                  email once one is live.
                </Text>
              )}
            </View>
          </>
        )}

        <Pressable onPress={backToSignIn} accessibilityRole="button" hitSlop={8}>
          <Text style={styles.link}>Already approved? Sign in</Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.xl, gap: spacing.lg, paddingBottom: spacing.xxl * 2 },
  kicker: { ...kicker },
  title: { color: colors.textPrimary, fontSize: typeScale.title, fontWeight: "700" },
  body: { color: colors.textSecondary, fontSize: typeScale.body, lineHeight: 22 },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  cardTitle: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700" },
  label: { color: colors.textPrimary, fontSize: typeScale.caption, fontWeight: "600" },
  input: {
    backgroundColor: colors.input,
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    color: colors.textPrimary,
    fontSize: typeScale.body,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  multiline: { minHeight: 88, textAlignVertical: "top" },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: spacing.md,
    minHeight: 48,
  },
  busy: { opacity: 0.7 },
  primaryText: { color: colors.onAccent, fontSize: typeScale.body, fontWeight: "700" },
  success: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600" },
  error: { color: colors.danger, fontSize: typeScale.caption },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 18 },
  format: { gap: spacing.xs },
  formatTitle: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600" },
  link: {
    color: colors.accent,
    fontSize: typeScale.body,
    fontWeight: "600",
    textAlign: "center",
    paddingVertical: spacing.sm,
  },
});
