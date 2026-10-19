/**
 * OpacitySlider — a dependency-free horizontal slider for the watermark opacity
 * (a fraction in [0, 1]). Built on React Native's View responder system
 * (`onResponder*` + `onLayout`) so it needs no native slider package. Tapping or
 * dragging anywhere on the track sets the value from the touch's x position.
 * Pure / controlled: the value is owned by the parent (immutable updates).
 */

import { useCallback, useState } from "react";
import {
  type GestureResponderEvent,
  type LayoutChangeEvent,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { WATERMARK_OPACITY_MAX, WATERMARK_OPACITY_MIN } from "@/lib/types";

const THUMB_SIZE = 22;

interface OpacitySliderProps {
  /** Current value in [0, 1]. */
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}

function clamp(value: number): number {
  return Math.max(WATERMARK_OPACITY_MIN, Math.min(WATERMARK_OPACITY_MAX, value));
}

export function OpacitySlider({
  value,
  onChange,
  disabled = false,
}: OpacitySliderProps) {
  const [width, setWidth] = useState(0);

  const onLayout = useCallback((e: LayoutChangeEvent) => {
    setWidth(e.nativeEvent.layout.width);
  }, []);

  const handleTouch = useCallback(
    (e: GestureResponderEvent) => {
      if (disabled || width <= 0) return;
      onChange(clamp(e.nativeEvent.locationX / width));
    },
    [disabled, width, onChange],
  );

  const pct = clamp(value);
  const percentLabel = `${Math.round(pct * 100)}%`;

  return (
    <View style={styles.wrap}>
      <View style={styles.header}>
        <Text style={styles.label}>Opacity</Text>
        <Text style={styles.value}>{percentLabel}</Text>
      </View>

      <View
        style={styles.hitArea}
        onLayout={onLayout}
        onStartShouldSetResponder={() => !disabled}
        onMoveShouldSetResponder={() => !disabled}
        onResponderGrant={handleTouch}
        onResponderMove={handleTouch}
        accessibilityRole="adjustable"
        accessibilityLabel="Watermark opacity"
        accessibilityValue={{ min: 0, max: 100, now: Math.round(pct * 100) }}
        accessibilityState={{ disabled }}
      >
        <View style={styles.track}>
          <View style={[styles.fill, { width: `${pct * 100}%` }]} />
        </View>
        <View
          style={[
            styles.thumb,
            disabled && styles.thumbDisabled,
            { left: `${pct * 100}%`, marginLeft: -THUMB_SIZE / 2 },
          ]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  label: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  value: { color: colors.textPrimary, fontSize: 13, fontWeight: "700" },
  // Extra vertical padding gives a comfortable touch target around the 6px track.
  hitArea: { justifyContent: "center", height: THUMB_SIZE + 12 },
  track: {
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.border,
    overflow: "hidden",
  },
  fill: { height: 6, backgroundColor: colors.primary },
  thumb: {
    position: "absolute",
    width: THUMB_SIZE,
    height: THUMB_SIZE,
    borderRadius: THUMB_SIZE / 2,
    backgroundColor: colors.primary,
    borderColor: colors.textPrimary,
    borderWidth: 2,
  },
  thumbDisabled: { backgroundColor: colors.muted },
});
