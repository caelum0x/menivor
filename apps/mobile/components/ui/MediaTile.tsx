/**
 * MediaTile primitive — image/video thumbnail tile for galleries and grids.
 * Shows a pressable image with optional label overlay. No emoji.
 */

import {
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing, weight } from "@/src/shared/theme";

export interface MediaTileProps {
  uri?: string;
  label?: string;
  subLabel?: string;
  aspectRatio?: number;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
}

export function MediaTile({
  uri,
  label,
  subLabel,
  aspectRatio = 9 / 16,
  onPress,
  style,
}: MediaTileProps): React.JSX.Element {
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? "button" : "image"}
      style={[styles.tile, style]}
    >
      {uri ? (
        <Image
          source={{ uri }}
          style={[styles.image, { aspectRatio }]}
          resizeMode="cover"
        />
      ) : (
        <View style={[styles.placeholder, { aspectRatio }]} />
      )}
      {(label || subLabel) ? (
        <View style={styles.overlay}>
          {label ? <Text style={styles.label} numberOfLines={2}>{label}</Text> : null}
          {subLabel ? <Text style={styles.subLabel} numberOfLines={1}>{subLabel}</Text> : null}
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  tile: {
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: colors.cardAlt,
    borderWidth: 1,
    borderColor: colors.border,
  },
  image: {
    width: "100%",
  },
  placeholder: {
    width: "100%",
    backgroundColor: colors.cardAlt,
  },
  overlay: {
    padding: spacing.sm,
    gap: 2,
  },
  label: {
    color: colors.textPrimary,
    fontSize: 12,
    fontWeight: weight.semibold,
  },
  subLabel: {
    color: colors.muted,
    fontSize: 11,
  },
});
