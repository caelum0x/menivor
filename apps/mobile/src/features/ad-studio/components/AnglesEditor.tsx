/** Editable ad angles. Edits stay local until the parent saves them. */

import { StyleSheet, Text, View } from "react-native";

import { Badge, TextField } from "@/components/ui";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

import type { AdAngle } from "../api";

type AngleField = "hook" | "pain" | "proof" | "offer" | "cta";

const FIELDS: readonly { key: AngleField; label: string }[] = [
  { key: "hook", label: "Hook" },
  { key: "pain", label: "Pain" },
  { key: "proof", label: "Proof" },
  { key: "offer", label: "Offer" },
  { key: "cta", label: "Call to action" },
];

/** Server cap on each angle field. */
const MAX_FIELD_LENGTH = 400;

export interface AnglesEditorProps {
  readonly angles: readonly AdAngle[];
  readonly onChange: (next: AdAngle[]) => void;
  readonly disabled?: boolean;
}

function sourceLabel(source: string): string {
  if (source === "llm") return "AI copy";
  if (source === "edited") return "Edited";
  return "Template";
}

export function AnglesEditor({ angles, onChange, disabled }: AnglesEditorProps) {
  const update = (index: number, key: AngleField, value: string) => {
    onChange(angles.map((angle, i) => (i === index ? { ...angle, [key]: value, source: "edited" } : angle)));
  };
  return (
    <View style={styles.list}>
      {angles.map((angle, index) => (
        <View key={angle.id || String(index)} style={styles.card}>
          <View style={styles.head}>
            <Text style={styles.title}>{angle.label}</Text>
            <Badge label={sourceLabel(angle.source)} variant={angle.source === "llm" ? "accent" : "neutral"} />
          </View>
          {FIELDS.map((field) => (
            <TextField
              key={field.key}
              label={field.label}
              value={angle[field.key]}
              onChangeText={(value) => update(index, field.key, value)}
              editable={!disabled}
              multiline={field.key !== "cta"}
              numberOfLines={2}
              maxLength={MAX_FIELD_LENGTH}
            />
          ))}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: spacing.md },
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.xs,
  },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  title: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700", flex: 1 },
});
