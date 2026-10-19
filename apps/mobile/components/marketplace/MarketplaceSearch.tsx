/**
 * Marketplace search + sort controls. A debounced-by-submit text query (the
 * parent decides when to fetch) plus a sort chip row (`top` | `new` | `clones`).
 * Presentational + local input state only; the parent (`app/marketplace.tsx`)
 * owns the query/sort state of record and the network call.
 */

import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import type { MarketplaceSort } from "@/lib/types";
import { colors } from "@/components/me/theme";

interface SortOption {
  key: MarketplaceSort;
  label: string;
}

const SORTS: readonly SortOption[] = [
  { key: "top", label: "Top rated" },
  { key: "new", label: "Newest" },
  { key: "clones", label: "Most cloned" },
];

interface MarketplaceSearchProps {
  query: string;
  onChangeQuery: (text: string) => void;
  /** Fired when the user submits the search field. */
  onSubmit: () => void;
  sort: MarketplaceSort;
  onChangeSort: (sort: MarketplaceSort) => void;
}

export function MarketplaceSearch({
  query,
  onChangeQuery,
  onSubmit,
  sort,
  onChangeSort,
}: MarketplaceSearchProps) {
  return (
    <View style={styles.wrap}>
      <TextInput
        style={styles.input}
        value={query}
        onChangeText={onChangeQuery}
        onSubmitEditing={onSubmit}
        placeholder="Search templates by title, description or tag"
        placeholderTextColor={colors.muted}
        maxLength={200}
        returnKeyType="search"
        autoCapitalize="none"
        autoCorrect={false}
      />

      <View style={styles.chips}>
        {SORTS.map((option) => {
          const active = option.key === sort;
          return (
            <Pressable
              key={option.key}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => onChangeSort(option.key)}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 12 },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary, fontSize: 13 },
  chipTextActive: { color: colors.textPrimary, fontWeight: "700" },
});
