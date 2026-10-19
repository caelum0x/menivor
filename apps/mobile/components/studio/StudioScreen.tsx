/**
 * StudioScreen — a full-screen container for the Studio (avatars & voices)
 * cluster. Standardises the page background plus the loading / error states so
 * each screen only renders its ready-state body (which owns its own list +
 * pull-to-refresh). Mirrors the Me tab's `SectionState`, scaled to a page.
 */

import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import type { ResourceStatus } from "@/components/me/use-resource";

interface StudioScreenProps {
  status: ResourceStatus;
  error: string;
  onRetry: () => void;
  /** Rendered only when `status === "ready"`. */
  children: ReactNode;
  loadingLabel?: string;
}

export function StudioScreen({
  status,
  error,
  onRetry,
  children,
  loadingLabel,
}: StudioScreenProps) {
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
      <View style={styles.center}>
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>
            {error || "Something went wrong."}
          </Text>
          <Pressable
            style={styles.retry}
            onPress={onRetry}
            accessibilityRole="button"
          >
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return <View style={styles.container}>{children}</View>;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
  },
  muted: { color: colors.muted, fontSize: 13 },
  errorBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
    alignItems: "flex-start",
    alignSelf: "stretch",
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
