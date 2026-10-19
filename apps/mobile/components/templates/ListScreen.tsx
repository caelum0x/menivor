/**
 * ListScreen<T> template — handles data-fetch + pull-to-refresh + loading /
 * empty / error lifecycle + optional search and filter chips.
 *
 * Usage: a typical list screen becomes ~30-50 lines. The caller only provides:
 *   - `fetcher` (stable memoized function returning Promise<T[]>)
 *   - `keyExtractor` and `renderItem`
 *   - optional `title`, `searchable`, `filterItems`, etc.
 *
 * Example:
 * ```tsx
 * const fetcher = useCallback(() => listVoices({ token }), [token]);
 *
 * return (
 *   <ListScreen
 *     fetcher={fetcher}
 *     keyExtractor={(v) => v.voice_id}
 *     renderItem={(v) => <VoiceCard voice={v} />}
 *     title="Voices"
 *     emptyTitle="No voices yet"
 *   />
 * );
 * ```
 */

import { useCallback, useMemo, useState } from "react";
import {
  FlatList,
  RefreshControl,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { isAbortError } from "@/lib/api";
import { useResource } from "@/components/me/use-resource";

import { Chip } from "../ui/Chip";
import { EmptyState } from "../ui/EmptyState";
import { ErrorState } from "../ui/ErrorState";
import { Header } from "../ui/Header";
import { Loading } from "../ui/Loading";
import { Screen } from "../ui/Screen";
import { SearchBar } from "../ui/SearchBar";
import { colors } from "@/components/me/theme";
import { spacing } from "@/src/shared/theme";

export interface FilterItem<F extends string = string> {
  id: F;
  label: string;
  badge?: number;
}

export interface ListScreenProps<T, F extends string = string> {
  /** Stable memoized async function that fetches the data. */
  fetcher: () => Promise<T[]>;
  keyExtractor: (item: T, index: number) => string;
  renderItem: (item: T, index: number) => React.JSX.Element;

  // Optional layout
  title?: string;
  headerAction?: React.JSX.Element;

  // Search
  searchable?: boolean;
  searchPlaceholder?: string;
  /** Return false to exclude an item from search results. */
  matchItem?: (item: T, query: string) => boolean;

  // Filters
  filterItems?: readonly FilterItem<F>[];
  activeFilter?: F;
  onFilterChange?: (id: F) => void;
  /** Called to check whether a data item passes the active filter. */
  filterItem?: (item: T, filterId: F) => boolean;

  // Empty/error
  emptyTitle?: string;
  emptyBody?: string;
  emptyActionLabel?: string;
  onEmptyAction?: () => void;

  style?: StyleProp<ViewStyle>;
}

export function ListScreen<T, F extends string = string>({
  fetcher,
  keyExtractor,
  renderItem,
  title,
  headerAction,
  searchable = false,
  searchPlaceholder = "Search…",
  matchItem,
  filterItems,
  activeFilter,
  onFilterChange,
  filterItem,
  emptyTitle = "Nothing here yet",
  emptyBody,
  emptyActionLabel,
  onEmptyAction,
  style,
}: ListScreenProps<T, F>): React.JSX.Element {
  const [query, setQuery] = useState("");
  const { status, data, error, reload } = useResource<T[]>(fetcher);
  const [refreshing, setRefreshing] = useState(false);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    reload();
    // Give the resource a tick to transition away from "loading"
    const id = setTimeout(() => setRefreshing(false), 800);
    return () => clearTimeout(id);
  }, [reload]);

  const filtered = useMemo<T[]>(() => {
    const source = data ?? [];
    let result = source;

    // Apply search
    if (searchable && query.trim() && matchItem) {
      const q = query.trim().toLowerCase();
      result = result.filter((item) => matchItem(item, q));
    }

    // Apply filter chip
    if (activeFilter && filterItem) {
      result = result.filter((item) => filterItem(item, activeFilter));
    }

    return result;
  }, [data, query, searchable, matchItem, activeFilter, filterItem]);

  const showFilters = filterItems && filterItems.length > 0;

  return (
    <Screen style={style} noPadding>
      {/* Title + filters header */}
      {(title || showFilters || searchable) ? (
        <View style={styles.topBar}>
          {title ? (
            <Header title={title} action={headerAction} style={styles.headerRow} />
          ) : null}
          {searchable ? (
            <SearchBar
              value={query}
              onChangeText={setQuery}
              placeholder={searchPlaceholder}
              style={styles.search}
            />
          ) : null}
          {showFilters ? (
            <View style={styles.filterRow}>
              {filterItems!.map((f) => (
                <Chip
                  key={f.id}
                  label={f.badge !== undefined ? `${f.label} (${f.badge})` : f.label}
                  active={f.id === activeFilter}
                  onPress={() => onFilterChange?.(f.id)}
                />
              ))}
            </View>
          ) : null}
        </View>
      ) : null}

      {/* Content */}
      {status === "loading" && !refreshing ? (
        <Loading />
      ) : status === "error" ? (
        <View style={styles.stateWrapper}>
          <ErrorState message={error} onRetry={reload} />
        </View>
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={keyExtractor}
          renderItem={({ item, index }) => renderItem(item, index)}
          contentContainerStyle={styles.content}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={colors.accent}
              colors={[colors.accent]}
            />
          }
          ListEmptyComponent={
            <EmptyState
              title={emptyTitle}
              body={emptyBody}
              actionLabel={emptyActionLabel}
              onAction={onEmptyAction}
            />
          }
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  topBar: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    gap: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerRow: { marginBottom: 0 },
  search: {},
  filterRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  stateWrapper: { padding: spacing.lg },
  content: { padding: spacing.lg, paddingBottom: spacing.xxl },
  separator: { height: spacing.sm },
});
