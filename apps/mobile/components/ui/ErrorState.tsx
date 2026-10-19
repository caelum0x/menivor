/**
 * ErrorState primitive — displays an error message with an optional retry button.
 * No emoji. Explicit types.
 */

import {
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { Button } from "./Button";
import { colors } from "@/components/me/theme";
import { radius, spacing } from "@/src/shared/theme";

export interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  style?: StyleProp<ViewStyle>;
}

export function ErrorState({
  message,
  onRetry,
  retryLabel = "Try again",
  style,
}: ErrorStateProps): React.JSX.Element {
  return (
    <View style={[styles.container, style]}>
      <Text style={styles.message}>{message || "Something went wrong."}</Text>
      {onRetry ? (
        <Button
          label={retryLabel}
          onPress={onRetry}
          variant="secondary"
          size="sm"
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
    alignItems: "flex-start",
  },
  message: {
    color: colors.error,
    fontSize: 14,
  },
});
