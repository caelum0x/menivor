/**
 * Screen primitive — full-screen safe-area wrapper with optional scroll and
 * header slot. Two variants:
 *   - <Screen> — plain non-scrolling (for FlatList screens)
 *   - <Screen scroll> — wraps content in a ScrollView with pull-to-refresh
 *
 * Uses react-native-safe-area-context for safe insets. No emoji.
 */

import type { ReactNode } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors } from "@/components/me/theme";
import { spacing } from "@/src/shared/theme";

export interface ScreenProps {
  children: ReactNode;
  /** Render children inside a ScrollView. */
  scroll?: boolean;
  /** Optional header element rendered above the content area. */
  header?: ReactNode;
  /** Pull-to-refresh is triggered when this is true → triggers onRefresh. */
  refreshing?: boolean;
  onRefresh?: () => void;
  style?: StyleProp<ViewStyle>;
  contentStyle?: StyleProp<ViewStyle>;
  /** Skip horizontal padding (useful for full-bleed lists). */
  noPadding?: boolean;
}

export function Screen({
  children,
  scroll = false,
  header,
  refreshing,
  onRefresh,
  style,
  contentStyle,
  noPadding = false,
}: ScreenProps): React.JSX.Element {
  const body = scroll ? (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={[
        styles.content,
        noPadding && styles.noPadding,
        contentStyle,
      ]}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefresh ? (
          <RefreshControl
            refreshing={refreshing ?? false}
            onRefresh={onRefresh}
            tintColor={colors.accent}
            colors={[colors.accent]}
          />
        ) : undefined
      }
    >
      {children}
    </ScrollView>
  ) : (
    <View
      style={[
        styles.content,
        noPadding && styles.noPadding,
        { flex: 1 },
        contentStyle,
      ]}
    >
      {children}
    </View>
  );

  return (
    <SafeAreaView style={[styles.safe, style]} edges={["left", "right", "bottom"]}>
      {header ? <View style={styles.header}>{header}</View> : null}
      {body}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  scroll: { flex: 1 },
  content: {
    padding: spacing.lg,
    paddingTop: spacing.xl,
  },
  noPadding: { padding: 0, paddingTop: 0 },
});
