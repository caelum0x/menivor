/**
 * Avatar primitive — circular image or fallback initials.
 * No emoji. Explicit types.
 */

import {
  Image,
  StyleSheet,
  Text,
  View,
  type ImageStyle,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { weight } from "@/src/shared/theme";

export type AvatarSize = "xs" | "sm" | "md" | "lg" | "xl";

const SIZE_MAP: Record<AvatarSize, number> = {
  xs: 24,
  sm: 32,
  md: 40,
  lg: 56,
  xl: 72,
};

export interface AvatarProps {
  /** Remote image URI. */
  uri?: string;
  /** Name used to derive initials when no image is available. */
  name?: string;
  size?: AvatarSize;
  style?: StyleProp<ImageStyle & ViewStyle>;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return (parts[0]?.slice(0, 2) ?? "?").toUpperCase();
  return `${parts[0]?.charAt(0) ?? ""}${parts[parts.length - 1]?.charAt(0) ?? ""}`.toUpperCase();
}

export function Avatar({
  uri,
  name = "",
  size = "md",
  style,
}: AvatarProps): React.JSX.Element {
  const dim = SIZE_MAP[size];
  const circle = { width: dim, height: dim, borderRadius: dim / 2 };

  if (uri) {
    return (
      <Image
        source={{ uri }}
        style={[styles.image, circle] as ImageStyle[]}
        accessibilityLabel={name || "Avatar"}
      />
    );
  }

  return (
    <View
      style={[styles.fallback, circle]}
      accessibilityLabel={name || "Avatar"}
    >
      <Text style={[styles.initials, { fontSize: dim * 0.34 }]}>
        {initials(name)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  image: { backgroundColor: colors.cardAlt },
  fallback: {
    backgroundColor: colors.cardAlt,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  initials: {
    color: colors.textSecondary,
    fontWeight: weight.bold,
  },
});
