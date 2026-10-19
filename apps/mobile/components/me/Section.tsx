/**
 * A titled section shell used by every block on the Me tab. Renders a section
 * header (title + optional right-hand action) and standardises the loading /
 * error presentation so each section only supplies its ready-state body.
 */

import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "./theme";
import type { ResourceStatus } from "./use-resource";

interface SectionProps {
  title: string;
  /** Optional element rendered on the right of the header (e.g. a refresh). */
  action?: ReactNode;
  children: ReactNode;
}

export function Section({ title, action, children }: SectionProps) {
  return (
    <View style={styles.section}>
      <View style={styles.header}>
        <Text style={styles.title}>{title}</Text>
        {action ?? null}
      </View>
      {children}
    </View>
  );
}

interface SectionStateProps {
  status: ResourceStatus;
  error: string;
  onRetry: () => void;
  /** Rendered only when `status === "ready"`. */
  children: ReactNode;
  loadingLabel?: string;
}

/**
 * Renders a spinner while loading, an inline error with a retry button on
 * failure, or the section body once ready.
 */
export function SectionState({
  status,
  error,
  onRetry,
  children,
  loadingLabel,
}: SectionStateProps) {
  if (status === "loading") {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
        {loadingLabel ? <Text style={styles.muted}>{loadingLabel}</Text> : null}
      </View>
    );
  }

  if (status === "error") {
    return (
      <View style={styles.errorBox}>
        <Text style={styles.errorText}>{error || "Something went wrong."}</Text>
        <Pressable style={styles.retry} onPress={onRetry}>
          <Text style={styles.retryText}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  return <>{children}</>;
}

const styles = StyleSheet.create({
  section: { gap: 12, marginBottom: 28 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  title: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 24, gap: 8 },
  muted: { color: colors.muted, fontSize: 13 },
  errorBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
    alignItems: "flex-start",
  },
  errorText: { color: colors.error, fontSize: 14 },
  retry: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  retryText: { color: colors.textSecondary, fontWeight: "600" },
});
