/**
 * A single horizontal bar rendered with pure RN primitives (no chart lib): a
 * track `View` with a filled `View` whose width is a percentage. Purely
 * presentational and reused by the time-series, funnel and breakdown widgets.
 */

import { StyleSheet, View } from "react-native";

import { colors } from "@/components/me/theme";

interface BarProps {
  /** Fill width as a percentage 0–100. */
  percent: number;
  /** Fill colour (defaults to the brand accent). */
  color?: string;
  /** Track height in px. */
  height?: number;
}

export function Bar({ percent, color, height = 10 }: BarProps) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <View
      style={[styles.track, { height, borderRadius: height / 2 }]}
      accessible={false}
    >
      <View
        style={[
          styles.fill,
          {
            width: `${clamped}%`,
            height,
            borderRadius: height / 2,
            backgroundColor: color ?? colors.accent,
          },
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    width: "100%",
    backgroundColor: colors.cardAlt,
    overflow: "hidden",
  },
  fill: { minWidth: 2 },
});
