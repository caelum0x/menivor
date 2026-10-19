import { useCallback, useEffect, useRef, useState } from "react";
import {
  Clipboard,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

/**
 * A labelled block of generated copy (title / caption / hashtags) with a "Copy"
 * button that writes the value to the system clipboard. Uses React Native's
 * built-in `Clipboard` (no extra dependency). The button flips to "Copied" for
 * a moment as feedback.
 *
 * `value` is what gets copied; `display` (when given) is what's shown — e.g.
 * hashtags are shown space-separated but copied the same way. An empty value
 * renders a muted placeholder and disables the button.
 */
export interface CopyableFieldProps {
  label: string;
  value: string;
  /** Optional display override; defaults to `value`. */
  display?: string;
  /** Shown (muted) when `value` is empty. */
  emptyText?: string;
}

const COPIED_RESET_MS = 1500;

export function CopyableField({
  label,
  value,
  display,
  emptyText = "None",
}: Readonly<CopyableFieldProps>) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasValue = value.trim().length > 0;

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const onCopy = useCallback(() => {
    if (!hasValue) return;
    Clipboard.setString(value);
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), COPIED_RESET_MS);
  }, [hasValue, value]);

  return (
    <View style={styles.field}>
      <View style={styles.header}>
        <Text style={styles.label}>{label}</Text>
        <Pressable
          style={[styles.copy, !hasValue && styles.copyDisabled]}
          onPress={onCopy}
          disabled={!hasValue}
          accessibilityRole="button"
          accessibilityLabel={`Copy ${label.toLowerCase()}`}
          accessibilityState={{ disabled: !hasValue }}
        >
          <Text style={styles.copyText}>{copied ? "Copied" : "Copy"}</Text>
        </Pressable>
      </View>
      <Text style={[styles.value, !hasValue && styles.valueEmpty]}>
        {hasValue ? display ?? value : emptyText}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  field: {
    backgroundColor: "#101018",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 8,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  label: {
    color: "#8b8b9b",
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  copy: {
    backgroundColor: "#2a2416",
    borderColor: "#E6C76A",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 6,
  },
  copyDisabled: { opacity: 0.4 },
  copyText: { color: "#E6C76A", fontSize: 12, fontWeight: "700" },
  value: { color: "#ece9e1", fontSize: 14, lineHeight: 20 },
  valueEmpty: { color: "#6f6c65" },
});
