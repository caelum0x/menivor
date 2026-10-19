/**
 * Loading and Skeleton primitives.
 *
 * - <Loading> — centered ActivityIndicator with optional label
 * - <Skeleton> — animated placeholder block (uses opacity cycling, no Reanimated)
 */

import { useEffect, useRef } from "react";
import {
  ActivityIndicator,
  Animated,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing } from "@/src/shared/theme";

// ---------------------------------------------------------------------------
// Loading indicator
// ---------------------------------------------------------------------------

export interface LoadingProps {
  label?: string;
  size?: "small" | "large";
  style?: StyleProp<ViewStyle>;
}

export function Loading({ label, size = "small", style }: LoadingProps): React.JSX.Element {
  return (
    <View style={[styles.center, style]}>
      <ActivityIndicator size={size} color={colors.accent} />
      {label ? <Text style={styles.label}>{label}</Text> : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Skeleton placeholder
// ---------------------------------------------------------------------------

export interface SkeletonProps {
  width?: number | `${number}%`;
  height?: number;
  borderRadius?: number;
  style?: StyleProp<ViewStyle>;
}

export function Skeleton({
  width = "100%",
  height = 16,
  borderRadius = radius.md,
  style,
}: SkeletonProps): React.JSX.Element {
  const opacity = useRef(new Animated.Value(0.4)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 0.8,
          duration: 800,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.4,
          duration: 800,
          useNativeDriver: true,
        }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [opacity]);

  return (
    <Animated.View
      style={[
        styles.skeleton,
        { width, height, borderRadius, opacity },
        style,
      ]}
    />
  );
}

/** A column of skeleton lines — useful for card placeholders. */
export interface SkeletonCardProps {
  lines?: number;
  style?: StyleProp<ViewStyle>;
}

export function SkeletonCard({ lines = 3, style }: SkeletonCardProps): React.JSX.Element {
  return (
    <View style={[styles.skeletonCard, style]}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          width={i === 0 ? "60%" : "100%"}
          height={i === 0 ? 18 : 13}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: spacing.xl,
    gap: spacing.sm,
  },
  label: { color: colors.muted, fontSize: 13 },
  skeleton: { backgroundColor: colors.cardAlt },
  skeletonCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
});
