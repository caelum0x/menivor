/** Small primary / ghost button used by the approvals and channel screens. */

import { ActivityIndicator, Pressable, Text } from "react-native";

import { colors } from "@/components/me/theme";
import { Icon, type IconName } from "@/components/ui/Icon";

import { ui } from "./styles";

export interface ActionButtonProps {
  label: string;
  onPress: () => void;
  variant?: "primary" | "ghost";
  disabled?: boolean;
  busy?: boolean;
  icon?: IconName;
  accessibilityLabel?: string;
}

export function ActionButton({
  label,
  onPress,
  variant = "primary",
  disabled = false,
  busy = false,
  icon,
  accessibilityLabel,
}: Readonly<ActionButtonProps>) {
  const ghost = variant === "ghost";
  const tint = ghost ? colors.textPrimary : colors.bg;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || busy}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: disabled || busy, busy }}
      style={[ui.button, ghost && ui.buttonGhost, (disabled || busy) && ui.disabled]}
    >
      {busy ? (
        <ActivityIndicator size="small" color={tint} />
      ) : icon ? (
        <Icon name={icon} size={16} color={tint} />
      ) : null}
      <Text style={[ui.buttonText, ghost && ui.buttonGhostText]}>{label}</Text>
    </Pressable>
  );
}
