/**
 * "Continue with email" on the sign-in panel: email -> 6-digit code -> signed
 * in. Collapsed to one button until tapped so Apple stays the first choice on
 * iOS. The parent owns the account step (onVerify), so an email session is
 * traded for a Menivor account exactly like Apple/Google.
 */
import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { Icon } from "@/components/ui/Icon";
import { colors } from "@/src/shared/theme";

import { EMAIL_CODE_LENGTH, normalizeEmail, normalizeEmailCode } from "./email-otp";

export interface EmailCodeSignInProps {
  /** Another sign-in is running; disable input. */
  busy: boolean;
  /** The verify/account step for this form is running. */
  verifying: boolean;
  onRequestCode: (email: string) => Promise<void>;
  onVerify: (email: string, code: string) => void;
}

type Step = "closed" | "email" | "code";

export function EmailCodeSignIn({ busy, verifying, onRequestCode, onVerify }: EmailCodeSignInProps) {
  const [step, setStep] = useState<Step>("closed");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sending, setSending] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const locked = busy || sending;

  const sendCode = async () => {
    const normalized = normalizeEmail(email);
    if (!normalized) {
      setNote("Enter a valid email address.");
      return;
    }
    setSending(true);
    setNote(null);
    try {
      await onRequestCode(normalized);
      setEmail(normalized);
      setCode("");
      setStep("code");
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Could not send the code. Try again.");
    } finally {
      setSending(false);
    }
  };

  const verify = () => {
    if (!normalizeEmailCode(code)) {
      setNote(`Enter the ${EMAIL_CODE_LENGTH}-digit code from the email.`);
      return;
    }
    setNote(null);
    onVerify(email, code);
  };

  if (step === "closed") {
    return (
      <Pressable
        style={[styles.button, busy && styles.dim]}
        onPress={() => setStep("email")}
        disabled={busy}
        accessibilityRole="button"
        accessibilityLabel="Continue with email"
      >
        <Icon name="mail-outline" size={18} color={colors.textPrimary} />
        <Text style={styles.buttonText}>Continue with email</Text>
      </Pressable>
    );
  }

  return (
    <View style={styles.box}>
      {step === "email" ? (
        <TextInput
          style={styles.input}
          value={email}
          onChangeText={setEmail}
          placeholder="you@company.com"
          placeholderTextColor={colors.textFaint}
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="email"
          keyboardType="email-address"
          textContentType="emailAddress"
          returnKeyType="send"
          onSubmitEditing={() => void sendCode()}
          editable={!locked}
          accessibilityLabel="Email address"
        />
      ) : (
        <>
          <Text style={styles.hint}>We sent a {EMAIL_CODE_LENGTH}-digit code to {email}.</Text>
          <TextInput
            style={styles.input}
            value={code}
            onChangeText={setCode}
            placeholder="123456"
            placeholderTextColor={colors.textFaint}
            keyboardType="number-pad"
            textContentType="oneTimeCode"
            autoComplete="one-time-code"
            maxLength={EMAIL_CODE_LENGTH + 2}
            returnKeyType="done"
            onSubmitEditing={verify}
            editable={!locked && !verifying}
            accessibilityLabel="Sign-in code"
          />
        </>
      )}

      <Pressable
        style={[styles.button, (locked || verifying) && styles.dim]}
        onPress={() => (step === "email" ? void sendCode() : verify())}
        disabled={locked || verifying}
        accessibilityRole="button"
      >
        {sending || verifying ? (
          <ActivityIndicator color={colors.textPrimary} />
        ) : (
          <Text style={styles.buttonText}>{step === "email" ? "Send code" : "Sign in"}</Text>
        )}
      </Pressable>

      {step === "code" ? (
        <Pressable
          onPress={() => {
            setStep("email");
            setNote(null);
          }}
          disabled={locked || verifying}
          accessibilityRole="button"
        >
          <Text style={styles.link}>Use a different email or resend</Text>
        </Pressable>
      ) : null}

      {note ? (
        <Text style={styles.note} accessibilityLiveRegion="polite">
          {note}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: 8 },
  button: {
    height: 52,
    borderRadius: 14,
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceAlt,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  buttonText: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  dim: { opacity: 0.5 },
  input: {
    minHeight: 46,
    paddingHorizontal: 12,
    borderRadius: 12,
    color: colors.textPrimary,
    backgroundColor: colors.input,
  },
  hint: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  link: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: "600",
    textAlign: "center",
    textDecorationLine: "underline",
  },
  note: { color: colors.textPrimary, fontSize: 13, lineHeight: 18 },
});
