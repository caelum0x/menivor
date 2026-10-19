/**
 * PositionSelector — a 2x2 grid of the four overlay corners a brand watermark
 * can sit in. Each cell mirrors its physical corner (top-left cell = top_left)
 * and shows a small dot in that corner so the choice reads at a glance. Pure /
 * controlled: selection state is owned by the parent (immutable updates).
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import {
  WATERMARK_POSITIONS,
  WATERMARK_POSITION_LABELS,
  type WatermarkPosition,
} from "@/lib/types";

interface PositionSelectorProps {
  value: WatermarkPosition | string;
  onChange: (position: WatermarkPosition) => void;
  disabled?: boolean;
}

/** Flex alignment for the preview dot inside a cell, per corner. */
const DOT_ALIGN: Record<
  WatermarkPosition,
  { justifyContent: "flex-start" | "flex-end"; alignItems: "flex-start" | "flex-end" }
> = {
  top_left: { justifyContent: "flex-start", alignItems: "flex-start" },
  top_right: { justifyContent: "flex-start", alignItems: "flex-end" },
  bottom_left: { justifyContent: "flex-end", alignItems: "flex-start" },
  bottom_right: { justifyContent: "flex-end", alignItems: "flex-end" },
};

export function PositionSelector({
  value,
  onChange,
  disabled = false,
}: PositionSelectorProps) {
  return (
    <View style={styles.grid}>
      {WATERMARK_POSITIONS.map((position) => {
        const active = position === value;
        return (
          <Pressable
            key={position}
            style={[styles.cell, active && styles.cellActive, disabled && styles.cellDisabled]}
            onPress={() => onChange(position)}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityLabel={WATERMARK_POSITION_LABELS[position]}
            accessibilityState={{ selected: active, disabled }}
          >
            <View style={[styles.dotWrap, DOT_ALIGN[position]]}>
              <View style={[styles.dot, active && styles.dotActive]} />
            </View>
            <Text style={[styles.label, active && styles.labelActive]}>
              {WATERMARK_POSITION_LABELS[position]}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  cell: {
    // Two per row: 50% width minus half the 10px gap.
    width: "47%",
    flexGrow: 1,
    height: 72,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    padding: 8,
    justifyContent: "space-between",
  },
  cellActive: { borderColor: colors.primary, backgroundColor: colors.cardAlt },
  cellDisabled: { opacity: 0.5 },
  dotWrap: { flex: 1 },
  dot: {
    width: 12,
    height: 12,
    borderRadius: 3,
    backgroundColor: colors.border,
  },
  dotActive: { backgroundColor: colors.primary },
  label: { color: colors.textSecondary, fontSize: 12, fontWeight: "600" },
  labelActive: { color: colors.textPrimary },
});
