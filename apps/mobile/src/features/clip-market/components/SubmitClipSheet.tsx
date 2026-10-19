/**
 * SubmitClipSheet — modal for a clipper to submit a clip URL to a chosen
 * campaign. Validates the URL client-side (`isHttpUrl`) then raises the trimmed
 * URL; the screen performs the idempotent POST and owns busy/error state.
 */

import * as React from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import type { Campaign } from "@/lib/clipmarket";

import { isHttpUrl } from "../logic";

export interface SubmitClipSheetProps {
  campaign: Campaign | null;
  submitting?: boolean;
  error?: string | null;
  onSubmit: (clipUrl: string) => void;
  onClose: () => void;
}

export function SubmitClipSheet({
  campaign,
  submitting = false,
  error = null,
  onSubmit,
  onClose,
}: SubmitClipSheetProps) {
  const [clipUrl, setClipUrl] = React.useState("");
  const [localError, setLocalError] = React.useState<string | null>(null);

  // Reset the field whenever a different campaign is targeted.
  React.useEffect(() => {
    setClipUrl("");
    setLocalError(null);
  }, [campaign?.id]);

  const onConfirm = React.useCallback(() => {
    if (!isHttpUrl(clipUrl)) {
      setLocalError("Enter a valid http(s) clip URL.");
      return;
    }
    setLocalError(null);
    onSubmit(clipUrl.trim());
  }, [clipUrl, onSubmit]);

  const visible = campaign !== null;
  const message = localError ?? error;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={styles.backdrop}>
        <View style={styles.sheet} testID="submit-clip-sheet">
          <Text style={styles.title}>Submit a clip</Text>
          <Text style={styles.subtitle} numberOfLines={1}>
            {campaign?.title || "Campaign"}
          </Text>
          <TextInput
            style={styles.input}
            placeholder="https://…"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            value={clipUrl}
            onChangeText={setClipUrl}
            testID="clip-url"
          />
          {message ? <Text style={styles.error}>{message}</Text> : null}

          <View style={styles.row}>
            <Pressable
              style={[styles.button, styles.cancel]}
              onPress={onClose}
              disabled={submitting}
              accessibilityRole="button"
              testID="clip-cancel"
            >
              <Text style={styles.cancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[styles.button, styles.confirm, submitting && styles.disabled]}
              onPress={onConfirm}
              disabled={submitting}
              accessibilityRole="button"
              testID="clip-confirm"
            >
              {submitting ? (
                <ActivityIndicator color={colors.bg} />
              ) : (
                <Text style={styles.confirmText}>Submit</Text>
              )}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.6)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: colors.card,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    padding: 20,
    gap: 12,
  },
  title: { color: colors.textPrimary, fontSize: 18, fontWeight: "800" },
  subtitle: { color: colors.textSecondary, fontSize: 13 },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 14,
  },
  error: { color: colors.error, fontSize: 13 },
  row: { flexDirection: "row", gap: 12, marginTop: 4 },
  button: {
    flex: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  cancel: { backgroundColor: colors.cardAlt, borderColor: colors.border, borderWidth: 1 },
  cancelText: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  confirm: { backgroundColor: colors.primary },
  confirmText: { color: colors.bg, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.6 },
});
