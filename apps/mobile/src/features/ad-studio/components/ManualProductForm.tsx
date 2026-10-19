/** Product details for stores that block automated page fetches. */

import { StyleSheet, View } from "react-native";

import { SelectField, TextField } from "@/components/ui";
import { spacing } from "@/src/shared/theme";

import { MANUAL_CURRENCIES, type ManualDraft } from "../api";

export interface ManualProductFormProps {
  readonly draft: ManualDraft;
  readonly onChange: (next: ManualDraft) => void;
  readonly disabled?: boolean;
}

export function ManualProductForm({ draft, onChange, disabled }: ManualProductFormProps) {
  const set = (key: keyof ManualDraft) => (value: string) => onChange({ ...draft, [key]: value });
  const editable = !disabled;
  return (
    <View style={styles.form}>
      <TextField label="Product name" required value={draft.title} onChangeText={set("title")} maxLength={200} editable={editable} />
      <TextField label="Brand" value={draft.brand} onChangeText={set("brand")} maxLength={80} editable={editable} />
      <View style={styles.row}>
        <TextField
          label="Price"
          value={draft.price}
          onChangeText={set("price")}
          keyboardType="decimal-pad"
          autoCapitalize="none"
          editable={editable}
          style={styles.flex}
        />
        <TextField
          label="Was"
          value={draft.originalPrice}
          onChangeText={set("originalPrice")}
          keyboardType="decimal-pad"
          autoCapitalize="none"
          editable={editable}
          style={styles.flex}
        />
      </View>
      <SelectField
        label="Currency"
        value={draft.currency}
        onChange={set("currency")}
        options={MANUAL_CURRENCIES.map((code) => ({ value: code, label: code }))}
        disabled={disabled}
      />
      <TextField
        label="Key features (one per line)"
        value={draft.bullets}
        onChangeText={set("bullets")}
        multiline
        numberOfLines={4}
        editable={editable}
      />
      <TextField
        label="Image URLs (one per line)"
        helper="Links to your product photos. Ads are rendered from these images."
        value={draft.images}
        onChangeText={set("images")}
        multiline
        numberOfLines={3}
        autoCapitalize="none"
        keyboardType="url"
        editable={editable}
      />
      <TextField
        label="Description"
        value={draft.description}
        onChangeText={set("description")}
        multiline
        numberOfLines={3}
        maxLength={2000}
        editable={editable}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  form: { gap: spacing.xs },
  row: { flexDirection: "row", gap: spacing.sm },
  flex: { flex: 1 },
});
