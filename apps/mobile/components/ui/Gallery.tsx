/**
 * Gallery primitive — a responsive grid FlatList.
 * Renders items in a fixed number of columns with even gutters.
 * No emoji. Explicit types with generics.
 */

import {
  FlatList,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { spacing } from "@/src/shared/theme";
import { EmptyState } from "./EmptyState";
import { Loading } from "./Loading";

export interface GalleryProps<T> {
  data: readonly T[];
  keyExtractor: (item: T, index: number) => string;
  renderItem: (item: T, index: number) => React.JSX.Element;
  numColumns?: number;
  loading?: boolean;
  loadingLabel?: string;
  emptyTitle?: string;
  emptyBody?: string;
  onRefresh?: () => void;
  refreshing?: boolean;
  style?: StyleProp<ViewStyle>;
  contentStyle?: StyleProp<ViewStyle>;
  gap?: number;
}

export function Gallery<T>({
  data,
  keyExtractor,
  renderItem,
  numColumns = 2,
  loading = false,
  loadingLabel,
  emptyTitle = "Nothing here yet",
  emptyBody,
  onRefresh,
  refreshing = false,
  style,
  contentStyle,
  gap = spacing.sm,
}: GalleryProps<T>): React.JSX.Element {
  if (loading) {
    return <Loading label={loadingLabel} style={style} />;
  }

  return (
    <FlatList
      data={data as T[]}
      keyExtractor={keyExtractor}
      numColumns={numColumns}
      columnWrapperStyle={numColumns > 1 ? { gap } : undefined}
      ItemSeparatorComponent={() => <View style={{ height: gap }} />}
      contentContainerStyle={[styles.content, contentStyle]}
      style={[styles.list, style]}
      renderItem={({ item, index }) => (
        <View style={{ flex: 1 / numColumns }}>
          {renderItem(item, index)}
        </View>
      )}
      ListEmptyComponent={
        <EmptyState title={emptyTitle} body={emptyBody} />
      }
      refreshing={refreshing}
      onRefresh={onRefresh}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    />
  );
}

const styles = StyleSheet.create({
  list: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
});
