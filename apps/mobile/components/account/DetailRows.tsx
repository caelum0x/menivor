/**
 * DetailRows — a small, presentational read-only key/value table used by the
 * account drill-in detail screens (avatars / voices / api-keys). Each row shows
 * an uppercase label and a selectable value; a row may opt into a "Copy" action
 * (RN's built-in `Clipboard`, no extra dependency) for values the user often
 * needs to paste elsewhere (an avatar/voice selector, a key prefix).
 *
 * Purely presentational and immutable — callers build the row list; this owns
 * only the transient "Copied" flash per row.
 */

import { useCallback, useRef, useState } from "react";
import { Clipboard, Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";

export interface DetailRow {
  label: string;
  value: string;
  /** When true, render a Copy affordance that writes `value` to the clipboard. */
  copyable?: boolean;
  /** Render the value in a monospace face (selectors, prefixes). */
  mono?: boolean;
}

interface DetailRowsProps {
  rows: readonly DetailRow[];
}

export function DetailRows({ rows }: DetailRowsProps) {
  const [copiedLabel, setCopiedLabel] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onCopy = useCallback((row: DetailRow) => {
    if (!row.value) return;
    Clipboard.setString(row.value);
    setCopiedLabel(row.label);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopiedLabel(null), 1500);
  }, []);

  return (
    <View style={styles.rows}>
      {rows.map((row, index) => (
        <View
          key={row.label}
          style={[styles.row, index === rows.length - 1 && styles.rowLast]}
        >
          <Text style={styles.label}>{row.label}</Text>
          <View style={styles.valueRow}>
            <Text
              style={[styles.value, row.mono && styles.mono]}
              selectable
              numberOfLines={3}
            >
              {row.value || "—"}
            </Text>
            {row.copyable && row.value ? (
              <Pressable
                style={styles.copy}
                onPress={() => onCopy(row)}
                hitSlop={8}
                accessibilityRole="button"
                accessibilityLabel={`Copy ${row.label}`}
              >
                <Text style={styles.copyText}>
                  {copiedLabel === row.label ? "Copied" : "Copy"}
                </Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  rows: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: "hidden",
  },
  row: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 4,
  },
  rowLast: { borderBottomWidth: 0 },
  label: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  valueRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  value: { color: colors.textPrimary, fontSize: 15, flexShrink: 1 },
  mono: { fontFamily: "monospace", fontSize: 13 },
  copy: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  copyText: { color: colors.accent, fontSize: 13, fontWeight: "700" },
});
