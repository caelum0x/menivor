/**
 * A row of five stars used both to DISPLAY a listing's aggregate rating and to
 * COLLECT the caller's own 1..5 rating. When `onRate` is provided each star is a
 * tappable target that reports its 1-based value; otherwise the row is a
 * read-only, fractional display of `value` (e.g. 3.6 -> three-and-a-half look).
 *
 * Presentational only: the parent owns the rate network call and any pending
 * state (passed via `disabled`). No secrets, no side effects.
 */

import { Pressable, StyleSheet, View } from "react-native";

import { Icon, type IconName } from "@/components/ui/Icon";

import {
  MAX_MARKETPLACE_STARS,
  MIN_MARKETPLACE_STARS,
} from "@/lib/types";
import { colors } from "@/components/me/theme";

interface StarRatingProps {
  /** Current rating (aggregate for display, or the caller's own selection). */
  value: number;
  /** When set, stars become tappable and report the chosen 1..5 value. */
  onRate?: (stars: number) => void;
  /** Disables interaction (e.g. while a rate call is in flight). */
  disabled?: boolean;
  /** Star glyph size in points. */
  size?: number;
}

const STARS: readonly number[] = Array.from(
  { length: MAX_MARKETPLACE_STARS - MIN_MARKETPLACE_STARS + 1 },
  (_, i) => MIN_MARKETPLACE_STARS + i,
);

export function StarRating({
  value,
  onRate,
  disabled = false,
  size = 18,
}: StarRatingProps) {
  const interactive = typeof onRate === "function";
  const rounded = Math.round(value);

  return (
    <View style={styles.row}>
      {STARS.map((star) => {
        // Half-star look for the read-only aggregate; whole stars when picking.
        const filled = interactive ? star <= rounded : star <= Math.round(value);
        const icon: IconName = filled ? "star" : "star-outline";
        const color = filled ? colors.accent : colors.muted;

        if (!interactive) {
          return (
            <Icon
              key={star}
              name={icon}
              size={size}
              color={color}
              style={styles.star}
            />
          );
        }

        return (
          <Pressable
            key={star}
            onPress={() => onRate?.(star)}
            disabled={disabled}
            hitSlop={6}
            accessibilityRole="button"
            accessibilityLabel={`Rate ${star} star${star === 1 ? "" : "s"}`}
          >
            <Icon
              name={icon}
              size={size}
              color={color}
              style={[styles.star, disabled && styles.disabled]}
            />
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: 2, alignItems: "center" },
  star: { fontWeight: "700" },
  disabled: { opacity: 0.5 },
});
