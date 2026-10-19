/**
 * Shared list scaffold for the catalog browser screens.
 *
 * Standardises the loading / error+retry / empty presentation and wires
 * pull-to-refresh, so each catalog screen only supplies its intro copy and a
 * row renderer. Generic over the item type; keeps the individual screens small.
 */

import type { ReactElement, ReactNode } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import type { ResourceStatus } from "@/components/me/use-resource";

interface CatalogListProps<T> {
  status: ResourceStatus;
  error: string;
  items: readonly T[];
  keyExtractor: (item: T, index: number) => string;
  renderItem: (item: T, index: number) => ReactElement;
  onRetry: () => void;
  refreshing: boolean;
  onRefresh: () => void;
  /** Intro copy rendered above the list (and above any empty/error state). */
  intro?: string;
  /** Optional element rendered between the intro and the list (e.g. filters). */
  header?: ReactNode;
  emptyTitle?: string;
  emptyBody?: string;
  loadingLabel?: string;
}

export function CatalogList<T>({
  status,
  error,
  items,
  keyExtractor,
  renderItem,
  onRetry,
  refreshing,
  onRefresh,
  intro,
  header,
  emptyTitle = "Nothing here yet",
  emptyBody = "This catalog is currently empty. Pull to refresh to check again.",
  loadingLabel,
}: CatalogListProps<T>): ReactElement {
  const listHeader = (
    <View>
      {intro ? <Text style={styles.intro}>{intro}</Text> : null}
      {header}
    </View>
  );

  if (status === "loading" && items.length === 0) {
    return (
      <View style={styles.container}>
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} />
          {loadingLabel ? <Text style={styles.muted}>{loadingLabel}</Text> : null}
        </View>
      </View>
    );
  }

  if (status === "error" && items.length === 0) {
    return (
      <View style={styles.container}>
        <View style={styles.content}>
          {intro ? <Text style={styles.intro}>{intro}</Text> : null}
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{error || "Something went wrong."}</Text>
            <Pressable style={styles.retry} onPress={onRetry} accessibilityRole="button">
              <Text style={styles.retryText}>Try again</Text>
            </Pressable>
          </View>
        </View>
      </View>
    );
  }

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={items as T[]}
      keyExtractor={keyExtractor}
      renderItem={({ item, index }) => renderItem(item, index)}
      ListHeaderComponent={listHeader}
      ListEmptyComponent={
        <View style={styles.emptyBox}>
          <Text style={styles.emptyTitle}>{emptyTitle}</Text>
          <Text style={styles.emptyBody}>{emptyBody}</Text>
        </View>
      }
      ListFooterComponent={<View style={styles.footer} />}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.accent}
          colors={[colors.accent]}
        />
      }
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16, lineHeight: 20 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 48, gap: 10 },
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
  emptyBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 20,
    gap: 6,
  },
  emptyTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  emptyBody: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  footer: { height: 32 },
});
