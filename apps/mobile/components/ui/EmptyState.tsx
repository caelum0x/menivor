/**
 * EmptyState primitive — shown when a list or section has no items.
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
import { spacing } from "@/src/shared/theme";

export interface EmptyStateProps {
  title: string;
  body?: string;
  /** Label for an optional action button. */
  actionLabel?: string;
  onAction?: () => void;
  style?: StyleProp<ViewStyle>;
}

export function EmptyState({
  title,
  body,
  actionLabel,
  onAction,
  style,
}: EmptyStateProps): React.JSX.Element {
  return (
    <View style={[styles.container, style]}>
      <Text style={styles.title}>{title}</Text>
      {body ? <Text style={styles.body}>{body}</Text> : null}
      {actionLabel && onAction ? (
        <Button
          label={actionLabel}
          onPress={onAction}
          variant="secondary"
          size="sm"
          style={styles.action}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  title: {
    color: colors.textSecondary,
    fontSize: 16,
    fontWeight: "700",
    textAlign: "center",
  },
  body: {
    color: colors.muted,
    fontSize: 13,
    textAlign: "center",
    maxWidth: 280,
  },
  action: { marginTop: spacing.sm },
});
