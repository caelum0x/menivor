/** Mobile management for real Mint-backed workspace, agent, and service recipients. */

import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useFocusEffect } from "expo-router";

import { colors } from "@/components/me/theme";
import {
  createWalletDestination,
  getWalletDestinationBalance,
  getWalletDestinations,
  getWalletSources,
  setWalletDestinationActive,
  type WalletDestinationBalance,
  type WalletDestinationProfile,
  type WalletDestinationProfileRequest,
  type WalletSource,
} from "@/lib/wallet";
import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";

type DestinationKind = WalletDestinationProfileRequest["kind"];
type DestinationScope = "personal" | "workspace";

function message(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Could not update receive identities.";
}

function formatTokens(micros: number): string {
  return `${(micros / 1_000_000).toLocaleString(undefined, {
    maximumFractionDigits: 6,
  })} AIT`;
}

export function WalletDestinationsScreen() {
  const { apiKey } = useSession();
  const options = useMemo(() => ({ token: apiKey ?? undefined }), [apiKey]);
  const [destinations, setDestinations] = useState<WalletDestinationProfile[]>([]);
  const [sources, setSources] = useState<WalletSource[]>([]);
  const [balances, setBalances] = useState<Record<string, WalletDestinationBalance>>({});
  const [kind, setKind] = useState<DestinationKind>("agent");
  const [scope, setScope] = useState<DestinationScope>("personal");
  const [workspaceSourceId, setWorkspaceSourceId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [slug, setSlug] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const workspaceSources = sources.filter((source) => source.kind === "workspace");
  const requiresWorkspace = kind === "workspace" || scope === "workspace";
  const normalizedSlug = slug.trim().toLowerCase();
  const valid = displayName.trim().length > 0
    && /^[a-z0-9](?:[a-z0-9-]{1,46}[a-z0-9])?$/.test(normalizedSlug)
    && (!requiresWorkspace || workspaceSourceId.length > 0);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [nextDestinations, nextSources] = await Promise.all([
        getWalletDestinations(options),
        getWalletSources(options),
      ]);
      setDestinations(nextDestinations);
      setSources(nextSources);
      const settled = await Promise.allSettled(
        nextDestinations.map((destination) =>
          getWalletDestinationBalance(destination.destination_id, options),
        ),
      );
      const nextBalances: Record<string, WalletDestinationBalance> = {};
      settled.forEach((result) => {
        if (result.status === "fulfilled") {
          nextBalances[result.value.destination.destination_id] = result.value;
        }
      });
      setBalances(nextBalances);
    } catch (cause) {
      setError(message(cause));
    }
  }, [options]);

  useFocusEffect(useCallback(() => {
    let active = true;
    setLoading(true);
    load().finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [load]));

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const submit = useCallback(async () => {
    if (!valid) return;
    setSubmitting(true);
    setError(null);
    try {
      const body: WalletDestinationProfileRequest = {
        kind,
        slug: normalizedSlug,
        display_name: displayName.trim(),
        ...(requiresWorkspace
          ? { workspace_source_account_id: workspaceSourceId }
          : {}),
      };
      const created = await createWalletDestination(body, options);
      setDestinations((current) => [...current, created]);
      setDisplayName("");
      setSlug("");
      const balance = await getWalletDestinationBalance(created.destination_id, options);
      setBalances((current) => ({ ...current, [created.destination_id]: balance }));
    } catch (cause) {
      setError(message(cause));
    } finally {
      setSubmitting(false);
    }
  }, [displayName, kind, normalizedSlug, options, requiresWorkspace, valid, workspaceSourceId]);

  const toggle = useCallback(async (destination: WalletDestinationProfile) => {
    setBusyId(destination.destination_id);
    setError(null);
    try {
      const updated = await setWalletDestinationActive(
        destination.destination_id,
        !destination.active,
        options,
      );
      setDestinations((current) => current.map((item) =>
        item.destination_id === updated.destination_id ? updated : item,
      ));
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusyId(null);
    }
  }, [options]);

  if (loading && destinations.length === 0) {
    return <View style={[styles.container, styles.center]}><ActivityIndicator color={colors.primary} /></View>;
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.primary} />}
    >
      <Text style={styles.title}>Receive identities</Text>
      <Text style={styles.subtitle}>
        Give a workspace, agent, or service its own public handle, Mint address, balance, and durable history.
      </Text>
      {error ? <Text style={styles.error}>{error}</Text> : null}

      <View style={styles.card}>
        <Text style={styles.label}>Identity type</Text>
        <View style={styles.choiceRow}>
          {(["agent", "service", "workspace"] as DestinationKind[]).map((value) => (
            <Pressable
              key={value}
              accessibilityRole="button"
              accessibilityState={{ selected: kind === value }}
              onPress={() => {
                setKind(value);
                if (value === "workspace") setScope("workspace");
              }}
              style={[styles.choice, kind === value && styles.choiceSelected]}
            >
              <Text style={[styles.choiceText, kind === value && styles.choiceTextSelected]}>{value}</Text>
            </Pressable>
          ))}
        </View>

        {kind !== "workspace" ? (
          <>
            <Text style={styles.label}>Owner</Text>
            <View style={styles.choiceRow}>
              {(["personal", "workspace"] as DestinationScope[]).map((value) => (
                <Pressable
                  key={value}
                  accessibilityRole="button"
                  accessibilityState={{ selected: scope === value }}
                  onPress={() => setScope(value)}
                  style={[styles.choice, scope === value && styles.choiceSelected]}
                >
                  <Text style={[styles.choiceText, scope === value && styles.choiceTextSelected]}>{value}</Text>
                </Pressable>
              ))}
            </View>
          </>
        ) : null}

        {requiresWorkspace ? (
          <>
            <Text style={styles.label}>Workspace</Text>
            {workspaceSources.length === 0 ? (
              <Text style={styles.hint}>You need an owner/admin workspace wallet before creating this identity.</Text>
            ) : workspaceSources.map((source) => (
              <Pressable
                key={source.source_account_id}
                accessibilityRole="button"
                accessibilityState={{ selected: workspaceSourceId === source.source_account_id }}
                onPress={() => setWorkspaceSourceId(source.source_account_id)}
                style={[styles.workspace, workspaceSourceId === source.source_account_id && styles.choiceSelected]}
              >
                <Text style={styles.workspaceName}>{source.label}</Text>
                <Text style={styles.hint}>{source.role}</Text>
              </Pressable>
            ))}
          </>
        ) : null}

        <Text style={styles.label}>Display name</Text>
        <TextInput
          accessibilityLabel="Destination display name"
          autoCapitalize="words"
          onChangeText={setDisplayName}
          placeholder="Caption Bot"
          placeholderTextColor={colors.textSecondary}
          style={styles.input}
          value={displayName}
        />
        <Text style={styles.label}>Public handle</Text>
        <View style={styles.handleRow}>
          <Text style={styles.prefix}>{kind}:</Text>
          <TextInput
            accessibilityLabel="Destination handle"
            autoCapitalize="none"
            autoCorrect={false}
            onChangeText={setSlug}
            placeholder="caption-bot"
            placeholderTextColor={colors.textSecondary}
            style={[styles.input, styles.handleInput]}
            value={slug}
          />
        </View>
        <Pressable
          accessibilityRole="button"
          disabled={!valid || submitting}
          onPress={submit}
          style={[styles.primaryButton, (!valid || submitting) && styles.disabled]}
        >
          <Text style={styles.primaryButtonText}>{submitting ? "Creating…" : "Create identity"}</Text>
        </Pressable>
      </View>

      <Text style={styles.sectionTitle}>Managed destinations</Text>
      {destinations.length === 0 ? <Text style={styles.empty}>No managed receive identities yet.</Text> : null}
      {destinations.map((destination) => {
        const balance = balances[destination.destination_id];
        return (
          <View key={destination.destination_id} style={styles.card}>
            <View style={styles.destinationHeader}>
              <View style={styles.destinationCopy}>
                <Text style={styles.handle}>{destination.handle}</Text>
                <Text style={styles.hint}>{destination.display_name} · {destination.scope}</Text>
              </View>
              <Pressable
                accessibilityRole="button"
                disabled={busyId === destination.destination_id}
                onPress={() => toggle(destination)}
                style={styles.secondaryButton}
              >
                <Text style={styles.secondaryButtonText}>{destination.active ? "Disable" : "Enable"}</Text>
              </Pressable>
            </View>
            <Text selectable style={styles.address}>{destination.address}</Text>
            <Text style={styles.balance}>
              {balance ? `${formatTokens(balance.available_micros)} available · ${formatTokens(balance.held_micros)} held` : "Balance unavailable"}
            </Text>
            {!destination.active ? <Text style={styles.inactive}>Receiving is disabled; history and funds remain intact.</Text> : null}
          </View>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { alignItems: "center", justifyContent: "center" },
  content: { padding: 20, paddingBottom: 48 },
  title: { color: colors.textPrimary, fontSize: 28, fontWeight: "700" },
  subtitle: { color: colors.textSecondary, fontSize: 14, lineHeight: 21, marginBottom: 20, marginTop: 8 },
  error: { color: colors.error, fontSize: 14, marginBottom: 14 },
  card: { backgroundColor: colors.card, borderColor: colors.border, borderRadius: 16, borderWidth: 1, marginBottom: 14, padding: 16 },
  label: { color: colors.textPrimary, fontSize: 13, fontWeight: "600", marginBottom: 7, marginTop: 12 },
  choiceRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  choice: { borderColor: colors.border, borderRadius: 999, borderWidth: 1, paddingHorizontal: 13, paddingVertical: 8 },
  choiceSelected: { borderColor: colors.primary, backgroundColor: `${colors.primary}18` },
  choiceText: { color: colors.textSecondary, fontSize: 13, textTransform: "capitalize" },
  choiceTextSelected: { color: colors.primary, fontWeight: "700" },
  workspace: { borderColor: colors.border, borderRadius: 10, borderWidth: 1, marginBottom: 7, padding: 11 },
  workspaceName: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  hint: { color: colors.textSecondary, fontSize: 12, marginTop: 3 },
  input: { borderColor: colors.border, borderRadius: 10, borderWidth: 1, color: colors.textPrimary, fontSize: 14, paddingHorizontal: 12, paddingVertical: 11 },
  handleRow: { alignItems: "center", flexDirection: "row" },
  prefix: { color: colors.textSecondary, fontFamily: "monospace", marginRight: 6 },
  handleInput: { flex: 1 },
  primaryButton: { alignItems: "center", backgroundColor: colors.primary, borderRadius: 11, marginTop: 16, paddingVertical: 13 },
  primaryButtonText: { color: colors.bg, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.45 },
  sectionTitle: { color: colors.textPrimary, fontSize: 17, fontWeight: "700", marginBottom: 10, marginTop: 12 },
  empty: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  destinationHeader: { alignItems: "flex-start", flexDirection: "row", justifyContent: "space-between" },
  destinationCopy: { flex: 1, marginRight: 12 },
  handle: { color: colors.textPrimary, fontFamily: "monospace", fontSize: 16, fontWeight: "700" },
  secondaryButton: { borderColor: colors.primary, borderRadius: 9, borderWidth: 1, paddingHorizontal: 11, paddingVertical: 7 },
  secondaryButtonText: { color: colors.primary, fontSize: 12, fontWeight: "600" },
  address: { color: colors.textSecondary, fontFamily: "monospace", fontSize: 12, marginTop: 14 },
  balance: { color: colors.textPrimary, fontSize: 13, fontWeight: "600", marginTop: 10 },
  inactive: { color: colors.error, fontSize: 12, marginTop: 8 },
});
