/**
 * CanonValueFields — the shared, presentational input group for a canon's value
 * surface (style, palette, typography, voice, product, brand). Controlled by the
 * parent screen: it renders labelled `TextInput`s and reports edits through
 * `onChange(key, value)`. List fields are entered comma-separated. Stateless so
 * both the create and lock forms render an identical surface.
 */

import { StyleSheet, Text, TextInput, View } from "react-native";

import { colors } from "@/components/me/theme";
import type { CanonValueFields as Fields } from "@/components/canon/canon-fields";

interface FieldSpec {
  key: keyof Fields;
  label: string;
  placeholder: string;
  hint?: string;
  multiline?: boolean;
}

const FIELD_SPECS: readonly FieldSpec[] = [
  { key: "style", label: "Style", placeholder: "e.g. cinematic, warm, editorial" },
  {
    key: "palette",
    label: "Palette",
    placeholder: "#0B0B0B, #FFD93D, #F5F5F5",
    hint: "Comma-separated colors or names",
  },
  {
    key: "typography",
    label: "Typography",
    placeholder: "Inter, Söhne",
    hint: "Comma-separated typefaces",
  },
  { key: "voice_id", label: "Voice ID", placeholder: "elevenlabs:…" },
  { key: "voice_tone", label: "Voice tone", placeholder: "confident, calm" },
  { key: "language", label: "Language", placeholder: "en, tr" },
  { key: "product_name", label: "Product name", placeholder: "Menivor" },
  {
    key: "product_descriptors",
    label: "Product descriptors",
    placeholder: "fast, private, on-device",
    hint: "Comma-separated",
  },
  {
    key: "product_claims",
    label: "Product claims",
    placeholder: "Renders in seconds, No account needed",
    hint: "Comma-separated approved claims",
    multiline: true,
  },
  {
    key: "brand_tone",
    label: "Brand tone",
    placeholder: "direct, playful",
    hint: "Comma-separated",
  },
  {
    key: "brand_avoid",
    label: "Brand avoid",
    placeholder: "hype, jargon",
    hint: "Comma-separated words/claims to avoid",
  },
];

interface CanonValueFieldsProps {
  fields: Fields;
  onChange: (key: keyof Fields, value: string) => void;
  disabled?: boolean;
}

export function CanonValueFields({ fields, onChange, disabled }: CanonValueFieldsProps) {
  return (
    <View style={styles.group}>
      {FIELD_SPECS.map((spec) => (
        <View key={spec.key} style={styles.field}>
          <Text style={styles.label}>{spec.label}</Text>
          <TextInput
            style={[styles.input, spec.multiline && styles.multiline]}
            value={fields[spec.key]}
            onChangeText={(text) => onChange(spec.key, text)}
            placeholder={spec.placeholder}
            placeholderTextColor={colors.muted}
            editable={!disabled}
            multiline={spec.multiline}
            autoCapitalize="none"
            autoCorrect={false}
          />
          {spec.hint ? <Text style={styles.hint}>{spec.hint}</Text> : null}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  group: { gap: 12 },
  field: { gap: 5 },
  label: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
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
  multiline: { minHeight: 72, textAlignVertical: "top" },
  hint: { color: colors.muted, fontSize: 11 },
});
