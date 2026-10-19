/**
 * Referral-code redeem form -> POST /me/referral/redeem. Surfaces submitting,
 * success, and guarded-failure states, and notifies the parent on a successful
 * grant so the referral stats can be refreshed.
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

import { redeemReferral } from "@/lib/api";
import type { RedeemResult } from "@/lib/types";

import { describeError } from "./errors";
import { colors } from "./theme";

interface RedeemFormProps {
  token: string | undefined;
  /** Called after a code is successfully redeemed (to refresh stats/credits). */
  onRedeemed: (result: RedeemResult) => void;
}

type SubmitState = "idle" | "submitting" | "success" | "error";

export function RedeemForm({ token, onRedeemed }: RedeemFormProps) {
  const [code, setCode] = useState("");
  const [state, setState] = useState<SubmitState>("idle");
  const [message, setMessage] = useState("");

  const submitting = state === "submitting";

  const onSubmit = async () => {
    const trimmed = code.trim();
    if (!trimmed) {
      setState("error");
      setMessage("Enter a referral code to redeem.");
      return;
    }
    setState("submitting");
    setMessage("");
    try {
      const result = await redeemReferral(trimmed, { token });
      if (!result.ok) {
        setState("error");
        setMessage(
          result.message || result.error || "That code couldn't be redeemed.",
        );
        return;
      }
      const granted =
        typeof result.referee_grant === "number" ? result.referee_grant : null;
      setState("success");
      setMessage(
        granted !== null && granted > 0
          ? `Redeemed! +${granted} credit${granted === 1 ? "" : "s"} added.`
          : result.message || "Referral code redeemed.",
      );
      setCode("");
      onRedeemed(result);
    } catch (err) {
      setState("error");
      setMessage(describeError(err, "Something went wrong redeeming the code."));
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.label}>Redeem a code</Text>
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          value={code}
          onChangeText={(text) => {
            setCode(text);
            if (state !== "idle") setState("idle");
          }}
          placeholder="e.g. REELXY42"
          placeholderTextColor={colors.muted}
          autoCapitalize="characters"
          autoCorrect={false}
          spellCheck={false}
          editable={!submitting}
        />
        <Pressable
          style={[styles.button, (submitting || !code.trim()) && styles.buttonDisabled]}
          onPress={onSubmit}
          disabled={submitting || !code.trim()}
        >
          {submitting ? (
            <ActivityIndicator color={colors.textPrimary} />
          ) : (
            <Text style={styles.buttonText}>Redeem</Text>
          )}
        </Pressable>
      </View>
      {state === "success" ? (
        <Text style={styles.success}>{message}</Text>
      ) : state === "error" ? (
        <Text style={styles.error}>{message}</Text>
      ) : null}
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
  row: { flexDirection: "row", gap: 8, alignItems: "center" },
  input: {
    flex: 1,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 12,
    paddingVertical: 10,
    letterSpacing: 1,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingHorizontal: 18,
    paddingVertical: 11,
    alignItems: "center",
    justifyContent: "center",
    minWidth: 92,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.textPrimary, fontWeight: "700" },
  success: { color: colors.success, fontSize: 13 },
  error: { color: colors.error, fontSize: 13 },
});
