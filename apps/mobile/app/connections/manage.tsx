/**
 * Connected Accounts — a full-screen manager for the creator's linked social
 * providers (TikTok / Instagram / YouTube). Lists every connectable provider
 * with its live status, runs the OAuth connect / reconnect handshake, and
 * disconnects (with confirmation + optimistic rollback). Pull-to-refresh
 * re-reads the token-free connection list from GET /me/connections.
 *
 * Deeper than the compact card on the Connections tab: a summary header, full
 * per-connection detail, and one-tap jumps to the publish + social-copy flows.
 *
 * NAV MANIFEST (for the integration agent):
 *   { route: "/connections/manage",     title: "Connected Accounts" }
 *   { route: "/connections/publish",    title: "Publish a Reel" }
 *   { route: "/connections/social-copy", title: "AI Social Copy" }
 *
 * SECURITY: no shape rendered here ever carries an access/refresh token — the
 * connection list and callback result are token-free. Auth flows through the
 * shared `x-api-key` session token; no secrets live in this screen.
 */

import { useCallback, useMemo, useState, type ReactElement } from "react";
import { Stack, useRouter } from "expo-router";
import {
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { disconnect as disconnectApi, getConnections } from "@/lib/api";
import { SOCIAL_PROVIDERS } from "@/lib/types";
import type { Connection, SocialProvider } from "@/lib/types";

import { ConnectionRow } from "@/components/connections/ConnectionRow";
import { providerLabel } from "@/components/connections/format";
import {
  ConnectCancelledError,
  connectProvider,
} from "@/components/connections/oauth";
import { SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { useSession } from "@/src/shared/auth";

export default function ConnectionsManageScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const fetcher = useCallback(() => getConnections({ token }), [token]);
  const { status, data, error, reload, setData } =
    useResource<Connection[]>(fetcher);

  const [refreshing, setRefreshing] = useState(false);
  const [busyProvider, setBusyProvider] = useState<string | null>(null);

  const connections = useMemo(() => data ?? [], [data]);
  const connectedCount = connections.length;

  const byProvider = useCallback(
    (provider: SocialProvider | string): Connection | undefined =>
      connections.find((c) => c.provider === provider),
    [connections],
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const next = await getConnections({ token });
      setData(() => next);
    } catch {
      // Surface via the section error the next time the query runs; a failed
      // manual refresh should not blow away the list already on screen.
    } finally {
      setRefreshing(false);
    }
  }, [token, setData]);

  const onConnect = useCallback(
    async (provider: SocialProvider | string) => {
      setBusyProvider(String(provider));
      try {
        const next = await connectProvider(provider, token);
        setData(() => next);
      } catch (err) {
        if (!(err instanceof ConnectCancelledError)) {
          Alert.alert(
            `Couldn't connect ${providerLabel(provider)}`,
            err instanceof Error ? err.message : "Failed to connect.",
          );
        }
      } finally {
        setBusyProvider(null);
      }
    },
    [token, setData],
  );

  const doDisconnect = useCallback(
    async (provider: SocialProvider | string) => {
      const previous = data;
      // Optimistically drop, confirm with the backend, roll back on failure.
      setData((prev) => (prev ?? []).filter((c) => c.provider !== provider));
      setBusyProvider(String(provider));
      try {
        await disconnectApi(provider, { token });
      } catch (err) {
        setData(() => previous);
        Alert.alert(
          `Couldn't disconnect ${providerLabel(provider)}`,
          err instanceof Error ? err.message : "Failed to disconnect.",
        );
      } finally {
        setBusyProvider(null);
      }
    },
    [token, data, setData],
  );

  const onDisconnect = useCallback(
    (provider: SocialProvider | string) => {
      Alert.alert(
        `Disconnect ${providerLabel(provider)}?`,
        "You'll need to reconnect before you can publish to this account again.",
        [
          { text: "Keep", style: "cancel" },
          {
            text: "Disconnect",
            style: "destructive",
            onPress: () => void doDisconnect(provider),
          },
        ],
        { cancelable: true },
      );
    },
    [doDisconnect],
  );

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: "Connected Accounts" }} />
      <FlatList
        data={SOCIAL_PROVIDERS}
        keyExtractor={(provider) => String(provider)}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void onRefresh()}
            tintColor={colors.accent}
          />
        }
        ListHeaderComponent={
          <View style={styles.headerBlock}>
            <Text style={styles.summary}>
              {connectedCount > 0
                ? `${connectedCount} of ${SOCIAL_PROVIDERS.length} accounts connected`
                : "No accounts connected yet"}
            </Text>
            <Text style={styles.intro}>
              Connecting opens the provider's secure login. We never see your
              password — only a revocable access grant is kept, and it is never
              shown here.
            </Text>
            <View style={styles.quickLinks}>
              <Pressable
                style={styles.linkBtn}
                onPress={() => router.push("/connections/publish")}
                accessibilityRole="link"
              >
                <Text style={styles.linkBtnText}>Publish a reel</Text>
              </Pressable>
              <Pressable
                style={styles.linkBtn}
                onPress={() => router.push("/connections/social-copy")}
                accessibilityRole="link"
              >
                <Text style={styles.linkBtnText}>AI social copy</Text>
              </Pressable>
            </View>
          </View>
        }
        renderItem={({ item: provider }) => (
          <View style={styles.rowWrap}>
            <ConnectionRow
              provider={provider}
              connection={byProvider(provider)}
              busy={busyProvider === provider}
              onConnect={(p) => void onConnect(p)}
              onDisconnect={onDisconnect}
            />
          </View>
        )}
        ListEmptyComponent={
          <SectionState
            status={status}
            error={error}
            onRetry={reload}
            loadingLabel="Loading your connections…"
          >
            <View />
          </SectionState>
        }
        // The provider list is fixed, so `status` gates the first paint only.
        ListFooterComponent={
          status === "error" && connectedCount === 0 ? null : (
            <View style={styles.spacer} />
          )
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, gap: 12 },
  headerBlock: { gap: 12, marginBottom: 4 },
  summary: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  intro: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  quickLinks: { flexDirection: "row", gap: 10 },
  linkBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
    backgroundColor: colors.card,
  },
  linkBtnText: { color: colors.accent, fontWeight: "700", fontSize: 13 },
  rowWrap: { marginBottom: 0 },
  spacer: { height: 40 },
});
