/**
 * Template Marketplace screen.
 *
 * Creators browse a PUBLIC catalog of published job templates, search by text or
 * tag, sort by rating / recency / clones, rate a listing 1..5 (one upserted
 * rating per user), and CLONE any listing into their own saved templates. The
 * list is fetched through the shared api client (auth token from the session,
 * sent as `x-api-key`); paging is bounded server-side (limit clamped 1..100).
 *
 * A single async resource owns the loading / ready / error lifecycle keyed on
 * the applied search + sort, so changing either re-fetches. Clone and rate apply
 * optimistic list updates (clone_count bump, rating refresh) that roll back on
 * failure. No secrets live here.
 */

import { useCallback, useState } from "react";
import {
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  browseMarketplace,
  cloneMarketplaceTemplate,
  rateMarketplaceTemplate,
} from "@/lib/api";
import { useSession } from "@/src/shared/auth";
import {
  DEFAULT_MARKETPLACE_LIMIT,
  type MarketplaceSort,
  type MarketplaceTemplate,
} from "@/lib/types";

import { SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { MarketplaceCard } from "@/components/marketplace/MarketplaceCard";
import { MarketplaceSearch } from "@/components/marketplace/MarketplaceSearch";

export default function MarketplaceScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  // Draft is what the user is typing; applied is what's actually been searched.
  const [queryDraft, setQueryDraft] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [sort, setSort] = useState<MarketplaceSort>("top");

  const fetcher = useCallback(
    () =>
      browseMarketplace({
        token,
        query: appliedQuery,
        sort,
        limit: DEFAULT_MARKETPLACE_LIMIT,
      }),
    [token, appliedQuery, sort],
  );
  const listings = useResource<MarketplaceTemplate[]>(fetcher);

  const onSubmitSearch = useCallback(() => {
    setAppliedQuery(queryDraft.trim());
  }, [queryDraft]);

  /** Clone a listing, then optimistically bump its clone count in the list. */
  const onClone = useCallback(
    async (id: string) => {
      await cloneMarketplaceTemplate(id, { token });
      listings.setData((rows) =>
        (rows ?? []).map((row) =>
          row.id === id ? { ...row, clone_count: row.clone_count + 1 } : row,
        ),
      );
    },
    [token, listings],
  );

  /** Upsert the caller's rating and merge the refreshed aggregate into the row. */
  const onRate = useCallback(
    async (id: string, stars: number) => {
      const updated = await rateMarketplaceTemplate(id, stars, { token });
      listings.setData((rows) =>
        (rows ?? []).map((row) =>
          row.id === id
            ? {
                ...row,
                rating_avg: updated.rating_avg,
                rating_count: updated.rating_count,
                viewer_stars: stars,
              }
            : row,
        ),
      );
    },
    [token, listings],
  );

  const data = listings.data ?? [];
  const isReady = listings.status === "ready";

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      data={data}
      keyExtractor={(item) => item.id}
      refreshControl={
        <RefreshControl
          refreshing={false}
          onRefresh={listings.reload}
          tintColor={colors.accent}
        />
      }
      ListHeaderComponent={
        <View style={styles.header}>
          <Text style={styles.intro}>
            Browse templates published by other creators. Clone one into your
            saved templates in a tap, or rate the ones you love.
          </Text>
          <MarketplaceSearch
            query={queryDraft}
            onChangeQuery={setQueryDraft}
            onSubmit={onSubmitSearch}
            sort={sort}
            onChangeSort={setSort}
          />
        </View>
      }
      renderItem={({ item }) => (
        <MarketplaceCard template={item} onClone={onClone} onRate={onRate} />
      )}
      ItemSeparatorComponent={() => <View style={styles.separator} />}
      ListEmptyComponent={
        <SectionState
          status={listings.status}
          error={listings.error}
          onRetry={listings.reload}
          loadingLabel="Loading templates…"
        >
          {isReady ? (
            <Text style={styles.muted}>
              {appliedQuery
                ? "No templates match your search."
                : "No templates published yet. Be the first to publish one."}
            </Text>
          ) : null}
        </SectionState>
      }
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24, gap: 12 },
  header: { gap: 16, marginBottom: 4 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  separator: { height: 12 },
  muted: { color: colors.muted, fontSize: 13 },
});
