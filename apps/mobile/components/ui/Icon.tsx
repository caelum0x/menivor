/**
 * App-wide icon primitive. Wraps Ionicons from @expo/vector-icons so screens
 * never fake icons with text glyphs (chevrons, crosses, arrows, checks). `style` accepts the same
 * text style the glyph used, so color/fontSize carry over unchanged; explicit
 * `color` / `size` props win when given.
 */

import type { ComponentProps } from "react";
import type { StyleProp, TextStyle } from "react-native";

import { Ionicons } from "@expo/vector-icons";

export type IconName = ComponentProps<typeof Ionicons>["name"];

export interface IconProps {
  readonly name: IconName;
  readonly size?: number;
  readonly color?: string;
  readonly style?: StyleProp<TextStyle>;
  /** Set when the icon carries meaning on its own (no adjacent label). */
  readonly accessibilityLabel?: string;
}

export function Icon({
  name,
  size = 18,
  color,
  style,
  accessibilityLabel,
}: IconProps) {
  return (
    <Ionicons
      name={name}
      size={size}
      {...(color ? { color } : {})}
      style={style}
      accessible={!!accessibilityLabel}
      accessibilityLabel={accessibilityLabel}
      importantForAccessibility={accessibilityLabel ? "yes" : "no-hide-descendants"}
    />
  );
}
