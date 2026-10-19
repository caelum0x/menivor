/**
 * Provider key vault (BYOK — bring-your-own-provider-key).
 *
 * The place to store YOUR OWN provider API keys (OpenRouter, ElevenLabs,
 * HeyGen, …) that Menivor's routing layer uses for renders when BYOK is
 * consented. Distinct from:
 *   - /account/developer-keys → platform REST API keys + resale gateway keys
 *   - /api-keys               → legacy platform API-key stub
 *   - /gateway                → resale keys
 *
 * Sections:
 *   OVERVIEW  active keys / providers covered / total renders on your keys.
 *   ADD KEY   form with provider quick-picks + free text, secret (write-only),
 *             optional label + routing priority; validated before submit.
 *   YOUR KEYS list with pull-to-refresh; each key shows the masked prefix,
 *             usage + priority metadata, and a confirmed revoke action.
 *
 * SECURITY: the raw secret is sent once and never returned by the API. This
 * screen never persists it — after a successful add the input is cleared.
 *
 * Endpoints wired: POST /byok/keys · GET /byok/keys · DELETE /byok/keys/{id}
 *
 * NAV MANIFEST: { route: "/account/provider-keys", title: "Provider Keys (BYOK)" }
 */

import * as React from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Stack } from "expo-router";

import { StatCard } from "@/components/me/StatCard";
import { colors } from "@/components/me/theme";
import { isAbortError } from "@/lib/api";
import {
  KNOWN_PROVIDERS,
  addProviderKey,
  deleteProviderKey,
  listProviderKeys,
  providerName,
  type ProviderKey,
} from "@/lib/byok";
import { useSession } from "@/src/shared/auth";

type LoadStatus = "loading" | "ready" | "error";

const MAX_PRIORITY = 100;

export default function ProviderKeysScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [keys, setKeys] = React.useState<readonly ProviderKey[]>([]);
  const [status, setStatus] = React.useState<LoadStatus>("loading");
  const [loadError, setLoadError] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);
  const [nonce, setNonce] = React.useState(0);

  const reload = React.useCallback(() => setNonce((n) => n + 1), []);

  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    if (nonce === 0) setStatus("loading");
    setLoadError("");
    listProviderKeys({ token, signal: controller.signal })
      .then((res) => {
        if (!active) return;
        setKeys(res.keys);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setLoadError(
          err instanceof Error ? err.message : "Provider keys are unavailable.",
        );
        setStatus("error");
      })
      .finally(() => {
        if (active) setRefreshing(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [token, nonce]);

  const onRefresh = React.useCallback(() => {
    setRefreshing(true);
    reload();
  }, [reload]);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.accent}
        />
      }
    >
      <Stack.Screen options={{ title: "Provider Keys (BYOK)" }} />
      <Text style={styles.intro}>
        Store your own provider API keys so renders run on your accounts and
        billing. Keys are encrypted at rest and used by the router only when
        bring-your-own-key is enabled. A secret is sent once and never shown
        again.
      </Text>

      <OverviewSection keys={keys} status={status} />

      <AddKeySection token={token} onAdded={reload} />

      <Text style={styles.sectionTitle}>Your keys</Text>
      {status === "loading" ? (
        <ActivityIndicator color={colors.accent} style={styles.spacer} />
      ) : status === "error" ? (
        <View style={styles.card}>
          <Text style={styles.error}>{loadError}</Text>
          <Pressable style={styles.retryButton} onPress={reload}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : keys.length === 0 ? (
        <View style={styles.card}>
          <Text style={styles.emptyTitle}>No provider keys yet</Text>
          <Text style={styles.meta}>
            Add a key above to route renders through your own provider account.
          </Text>
        </View>
      ) : (
        keys.map((item) => (
          <ProviderKeyCard
            key={item.id}
            item={item}
            token={token}
            onChanged={reload}
          />
        ))
      )}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

function OverviewSection({
  keys,
  status,
}: {
  keys: readonly ProviderKey[];
  status: LoadStatus;
}): React.ReactElement | null {
  if (status !== "ready") return null;

  const activeKeys = keys.filter((k) => k.status === "active");
  const providersCovered = new Set(activeKeys.map((k) => k.provider_key)).size;
  const totalUses = keys.reduce((sum, k) => sum + (k.use_count || 0), 0);

  return (
    <View style={styles.statRow}>
      <StatCard
        label="Active keys"
        value={activeKeys.length.toLocaleString()}
        accent={colors.accent}
      />
      <StatCard
        label="Providers covered"
        value={providersCovered.toLocaleString()}
      />
      <StatCard
        label="Renders on your keys"
        value={totalUses.toLocaleString()}
        hint="Lifetime uses"
      />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Add key form
// ---------------------------------------------------------------------------

function AddKeySection({
  token,
  onAdded,
}: {
  token: string | undefined;
  onAdded: () => void;
}): React.ReactElement {
  const [provider, setProvider] = React.useState("");
  const [secret, setSecret] = React.useState("");
  const [label, setLabel] = React.useState("");
  const [priority, setPriority] = React.useState("0");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState("");

  const resetError = React.useCallback(() => {
    setError("");
    setSuccess("");
  }, []);

  const validate = React.useCallback((): {
    provider_key: string;
    secret: string;
    label: string;
    priority: number;
  } | null => {
    const providerKey = provider.trim();
    const rawSecret = secret.trim();
    if (providerKey.length === 0) {
      setError("Choose or type a provider.");
      return null;
    }
    if (rawSecret.length === 0) {
      setError("Paste the provider secret key.");
      return null;
    }
    const priorityNum = Number.parseInt(priority || "0", 10);
    if (!Number.isFinite(priorityNum) || priorityNum < 0) {
      setError("Priority must be zero or a positive whole number.");
      return null;
    }
    if (priorityNum > MAX_PRIORITY) {
      setError(`Priority must be ${MAX_PRIORITY} or lower.`);
      return null;
    }
    return {
      provider_key: providerKey,
      secret: rawSecret,
      label: label.trim(),
      priority: priorityNum,
    };
  }, [provider, secret, label, priority]);

  const onSubmit = React.useCallback(async (): Promise<void> => {
    resetError();
    const body = validate();
    if (body === null) return;
    setSubmitting(true);
    try {
      const created = await addProviderKey(body, { token });
      setSuccess(
        `Stored ${providerName(created.provider_key)} key (${
          created.key_prefix || "hidden"
        }).`,
      );
      // Never keep the secret in memory after a successful store.
      setSecret("");
      setLabel("");
      setPriority("0");
      onAdded();
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Could not store the key.",
      );
    } finally {
      setSubmitting(false);
    }
  }, [validate, resetError, token, onAdded]);

  return (
    <View>
      <Text style={styles.sectionTitle}>Add a provider key</Text>
      <View style={styles.card}>
        <Text style={styles.fieldLabel}>Provider</Text>
        <View style={styles.chipRow}>
          {KNOWN_PROVIDERS.map((p) => {
            const selected = provider.trim() === p.key;
            return (
              <Pressable
                key={p.key}
                style={[styles.chip, selected && styles.chipSelected]}
                onPress={() => {
                  setProvider(p.key);
                  resetError();
                }}
                accessibilityRole="button"
                accessibilityState={{ selected }}
                accessibilityLabel={`Provider ${p.name}`}
              >
                <Text
                  style={[styles.chipText, selected && styles.chipTextSelected]}
                >
                  {p.name}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <TextInput
          style={styles.input}
          placeholder="Provider slug (e.g. openrouter)"
          placeholderTextColor={colors.muted}
          value={provider}
          onChangeText={(text) => {
            setProvider(text);
            resetError();
          }}
          autoCapitalize="none"
          autoCorrect={false}
          maxLength={64}
        />

        <Text style={styles.fieldLabel}>Secret key</Text>
        <TextInput
          style={styles.input}
          placeholder="Paste the provider API key"
          placeholderTextColor={colors.muted}
          value={secret}
          onChangeText={(text) => {
            setSecret(text);
            resetError();
          }}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
          maxLength={512}
        />

        <Text style={styles.fieldLabel}>Label (optional)</Text>
        <TextInput
          style={styles.input}
          placeholder="e.g. Personal OpenRouter"
          placeholderTextColor={colors.muted}
          value={label}
          onChangeText={setLabel}
          maxLength={100}
        />

        <Text style={styles.fieldLabel}>Routing priority</Text>
        <TextInput
          style={styles.input}
          placeholder="0"
          placeholderTextColor={colors.muted}
          keyboardType="number-pad"
          value={priority}
          onChangeText={(text) => {
            setPriority(text.replace(/[^0-9]/g, ""));
            resetError();
          }}
          maxLength={3}
        />
        <Text style={styles.helper}>
          Higher priority wins when several keys exist for the same provider.
        </Text>

        <Pressable
          style={[styles.button, submitting && styles.disabled]}
          disabled={submitting}
          onPress={() => void onSubmit()}
          accessibilityRole="button"
          accessibilityLabel="Store provider key"
        >
          <Text style={styles.buttonText}>
            {submitting ? "Storing…" : "Store key"}
          </Text>
        </Pressable>

        {error ? <Text style={styles.error}>{error}</Text> : null}
        {success ? <Text style={styles.success}>{success}</Text> : null}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Key row
// ---------------------------------------------------------------------------

function ProviderKeyCard({
  item,
  token,
  onChanged,
}: {
  item: ProviderKey;
  token: string | undefined;
  onChanged: () => void;
}): React.ReactElement {
  const [revoking, setRevoking] = React.useState(false);
  const [error, setError] = React.useState("");
  const revoked = item.status !== "active";

  const onRevoke = React.useCallback((): void => {
    const name = item.label || providerName(item.provider_key);
    Alert.alert(
      "Revoke provider key",
      `Revoke "${name}"? Renders stop using it immediately and fall back to the platform key. This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Revoke",
          style: "destructive",
          onPress: () => {
            setError("");
            setRevoking(true);
            deleteProviderKey(item.id, { token })
              .then(() => onChanged())
              .catch((err: unknown) => {
                setError(
                  err instanceof Error ? err.message : "Could not revoke the key.",
                );
              })
              .finally(() => setRevoking(false));
          },
        },
      ],
    );
  }, [item.id, item.label, item.provider_key, token, onChanged]);

  return (
    <View style={[styles.card, revoked && styles.cardDisabled]}>
      <View style={styles.rowBetween}>
        <Text style={styles.name} numberOfLines={1}>
          {item.label || providerName(item.provider_key)}
        </Text>
        {revoked ? <Text style={styles.revokedTag}>Revoked</Text> : null}
      </View>
      <Text style={styles.providerLine}>
        {providerName(item.provider_key)}
        {item.label ? ` · ${item.provider_key}` : ""}
      </Text>
      <Text style={styles.mono} selectable>
        {item.key_prefix || "•••"}
      </Text>
      <Text style={styles.meta}>
        Priority {item.priority} · {item.use_count.toLocaleString()} uses
        {item.last_used_at ? ` · last used ${formatDate(item.last_used_at)}` : ""}
      </Text>
      {item.created_at ? (
        <Text style={styles.metaFaint}>Added {formatDate(item.created_at)}</Text>
      ) : null}

      {!revoked ? (
        <Pressable
          style={[styles.revokeButton, revoking && styles.disabled]}
          disabled={revoking}
          onPress={onRevoke}
          accessibilityRole="button"
          accessibilityLabel={`Revoke ${item.label || providerName(item.provider_key)}`}
        >
          <Text style={styles.revokeText}>
            {revoking ? "Revoking…" : "Revoke key"}
          </Text>
        </Pressable>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 12,
  },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "700",
    marginTop: 20,
    marginBottom: 12,
  },
  statRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
    marginBottom: 4,
  },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  cardDisabled: { opacity: 0.6 },
  fieldLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "600",
    marginBottom: 6,
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginBottom: 12,
  },
  chip: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  chipSelected: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  chipText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  chipTextSelected: { color: colors.bg },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    color: colors.textPrimary,
    padding: 10,
    marginBottom: 12,
  },
  helper: {
    color: colors.muted,
    fontSize: 12,
    marginTop: -4,
    marginBottom: 12,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    padding: 12,
    alignItems: "center",
  },
  buttonText: { color: colors.bg, fontWeight: "700" },
  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  name: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "600",
    flexShrink: 1,
    paddingRight: 8,
  },
  providerLine: { color: colors.textSecondary, fontSize: 13, marginTop: 4 },
  revokedTag: { color: colors.error, fontSize: 11, fontWeight: "700" },
  mono: {
    color: colors.textPrimary,
    fontSize: 13,
    fontFamily: "monospace",
    marginTop: 6,
  },
  meta: { color: colors.muted, fontSize: 12, marginTop: 6 },
  metaFaint: { color: colors.muted, fontSize: 11, marginTop: 2, opacity: 0.8 },
  emptyTitle: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "600",
    marginBottom: 6,
  },
  revokeButton: {
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    marginTop: 12,
  },
  revokeText: { color: colors.error, fontSize: 13, fontWeight: "600" },
  retryButton: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    marginTop: 10,
  },
  retryText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  disabled: { opacity: 0.5 },
  error: { color: colors.error, fontSize: 13, marginTop: 8 },
  success: { color: colors.success, fontSize: 13, marginTop: 8 },
  spacer: { height: 24 },
});
