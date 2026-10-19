/**
 * Reel-create picker for A/B variations of the reel to fan out in one
 * batch (1..MAX_JOB_VARIANTS). Each extra variant is a separate job that spends
 * its own credit, so the helper copy makes the cost implication clear. Emits the
 * chosen count upward. Pure/controlled — no data fetching.
 */
import { Pressable, StyleSheet, Text, View } from "react-native";

import { MAX_JOB_VARIANTS } from "@/lib/types";
import { Icon } from "@/components/ui/Icon";

interface VariantsStepperProps {
  value: number;
  onChange: (variants: number) => void;
  disabled?: boolean;
}

const MIN = 1;

export function VariantsStepper({
  value,
  onChange,
  disabled = false,
}: VariantsStepperProps) {
  const clamp = (n: number): number =>
    Math.max(MIN, Math.min(MAX_JOB_VARIANTS, n));

  const decDisabled = disabled || value <= MIN;
  const incDisabled = disabled || value >= MAX_JOB_VARIANTS;

  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Fewer variations"
          style={[styles.step, decDisabled && styles.stepDisabled]}
          onPress={() => onChange(clamp(value - 1))}
          disabled={decDisabled}
        >
          <Icon name="remove" style={styles.stepText} />
        </Pressable>

        <View style={styles.valueBox}>
          <Text style={styles.value}>{value}</Text>
          <Text style={styles.valueLabel}>
            {value === 1 ? "reel" : "variations"}
          </Text>
        </View>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="More variations"
          style={[styles.step, incDisabled && styles.stepDisabled]}
          onPress={() => onChange(clamp(value + 1))}
          disabled={incDisabled}
        >
          <Icon name="add" style={styles.stepText} />
        </Pressable>
      </View>

      <Text style={styles.hint}>
        {value > 1
          ? `We'll render ${value} independent variations so you can pick the best — each uses one credit.`
          : "Generate a single reel using one credit."}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  row: { flexDirection: "row", alignItems: "center", gap: 12 },
  step: {
    width: 48,
    height: 48,
    borderRadius: 12,
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  stepDisabled: { opacity: 0.4 },
  stepText: { color: "#ffffff", fontSize: 24, fontWeight: "700", lineHeight: 26 },
  valueBox: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 8,
  },
  value: { color: "#ffffff", fontSize: 22, fontWeight: "800" },
  valueLabel: { color: "#6f6c65", fontSize: 12, marginTop: 2 },
  hint: { color: "#6f6c65", fontSize: 13 },
});
