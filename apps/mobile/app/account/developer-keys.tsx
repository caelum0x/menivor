/**
 * Developer & API keys (account/dev cluster).
 *
 * The canonical integration hub (legacy /developer, /usage, /api-keys and
 * /account/api-keys redirect here) with caller-scoped sections:
 *   - OVERVIEW: the developer portal footprint (active keys, requests this
 *     month, workspaces, webhook subscriptions) from GET /me/developer.
 *   - API KEYS: personal REST API keys — create (raw secret revealed ONCE),
 *     list (prefix + last-used), and revoke — over POST/GET/DELETE /me/api-keys.
 *     Each key opens its detail (/account/api-keys/[id]: metadata, usage
 *     history, revoke).
 *   - API USAGE: each key's calendar-month requests vs quota + rate limit
 *     (GET /me/api-keys/usage).
 *   - WEBHOOKS: link to /account/webhooks (per-workspace subscriptions,
 *     signed test events, deliveries, revoke).
 *   - RESALE GATEWAY: provisioning keys for reselling generation under a daily
 *     cap + markup — create (secret revealed ONCE), quote a base cost, and
 *     revoke — over the /gateway/keys endpoints.
 *
 * SECURITY: every raw secret (API key / gateway key) is shown EXACTLY ONCE at
 * creation and never persisted here; the server keeps only a hash. Auth flows
 * through the shared `x-api-key` client via the session token.
 *
 * NAV MANIFEST: { route: "/account/developer-keys", title: "Developer & API Keys" }
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

import { Stack, useRouter } from "expo-router";

import { StatCard } from "@/components/me/StatCard";
import { Icon } from "@/components/ui/Icon";
import { UsageManager } from "@/components/usage/UsageManager";
import { colors } from "@/components/me/theme";
import {
  createApiKey,
  isAbortError,
  listApiKeys,
  revokeApiKey,
} from "@/lib/api";
import {
  getDeveloperPortal,
  type DeveloperPortal,
} from "@/lib/developer";
import {
  createKey,
  listKeys,
  quoteKey,
  revokeKey,
  usd,
  type KeyQuote,
  type ProvisioningKey,
} from "@/lib/gateway";
import type { ApiKey } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

type LoadStatus = "loading" | "ready" | "error";

export default function DeveloperKeysScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [nonce, setNonce] = React.useState(0);
  const reloadAll = React.useCallback(() => setNonce((n) => n + 1), []);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={false}
          onRefresh={reloadAll}
          tintColor={colors.accent}
        />
      }
    >
      <Stack.Screen options={{ title: "Developer & API Keys" }} />
      <Text style={styles.intro}>
        Integrate Menivor into your own stack. Send an API key as the{" "}
        <Text style={styles.code}>x-api-key</Text> header. A minted key or resale
        secret is shown once — copy it before you leave.
      </Text>

      <OverviewSection token={token} nonce={nonce} />
      <ApiKeysSection token={token} nonce={nonce} />
      <UsageManager key={`usage-${nonce}`} token={token} />
      <WebhooksLink />
      <GatewaySection token={token} nonce={nonce} />

      <View style={styles.spacer} />
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

function OverviewSection({
  token,
  nonce,
}: {
  token: string | undefined;
  nonce: number;
}): React.ReactElement {
  const [portal, setPortal] = React.useState<DeveloperPortal | null>(null);
  const [status, setStatus] = React.useState<LoadStatus>("loading");
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setStatus("loading");
    setError("");
    getDeveloperPortal({ token, signal: controller.signal })
      .then((res) => {
        if (!active) return;
        setPortal(res);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setError(
          err instanceof Error ? err.message : "Overview is unavailable.",
        );
        setStatus("error");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [token, nonce]);

  return (
    <View>
      <Text style={styles.sectionTitle}>Overview</Text>
      {status === "loading" ? (
        <ActivityIndicator color={colors.accent} style={styles.spacer} />
      ) : status === "error" ? (
        <Text style={styles.error}>{error}</Text>
      ) : portal ? (
        <>
          <View style={styles.statRow}>
            <View style={styles.flex}>
              <StatCard
                label="Active keys"
                value={portal.api_keys.active.toLocaleString()}
                accent={colors.accent}
              />
            </View>
            <View style={styles.flex}>
              <StatCard
                label="Requests this month"
                value={portal.api_keys.requests_this_month.toLocaleString()}
              />
            </View>
          </View>
          <View style={styles.statRow}>
            <View style={styles.flex}>
              <StatCard
                label="Workspaces"
                value={portal.workspaces.toLocaleString()}
              />
            </View>
            <View style={styles.flex}>
              <StatCard
                label="Webhook subs"
                value={portal.webhooks.active.toLocaleString()}
                hint={`${portal.webhooks.total} total`}
              />
            </View>
          </View>
          {portal.api_base_url ? (
            <View style={styles.card}>
              <Text style={styles.fieldLabel}>API base</Text>
              <Text style={styles.mono} selectable>
                {portal.api_base_url}
              </Text>
              {portal.docs_url ? (
                <>
                  <Text style={[styles.fieldLabel, styles.spaced]}>Docs</Text>
                  <Text style={styles.mono} selectable>
                    {portal.docs_url}
                  </Text>
                </>
              ) : null}
              {portal.api_version ? (
                <Text style={styles.meta}>API version {portal.api_version}</Text>
              ) : null}
            </View>
          ) : null}
        </>
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Personal API keys
// ---------------------------------------------------------------------------

function ApiKeysSection({
  token,
  nonce,
}: {
  token: string | undefined;
  nonce: number;
}): React.ReactElement {
  const [keys, setKeys] = React.useState<readonly ApiKey[]>([]);
  const [status, setStatus] = React.useState<LoadStatus>("loading");
  const [error, setError] = React.useState("");
  const router = useRouter();
  const [localNonce, setLocalNonce] = React.useState(0);
  const reload = React.useCallback(() => setLocalNonce((n) => n + 1), []);

  const [name, setName] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const [secret, setSecret] = React.useState("");

  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setStatus("loading");
    setError("");
    listApiKeys({ token, signal: controller.signal })
      .then((rows) => {
        if (!active) return;
        setKeys(rows);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setError(err instanceof Error ? err.message : "Keys are unavailable.");
        setStatus("error");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [token, nonce, localNonce]);

  const onCreate = React.useCallback(async (): Promise<void> => {
    const trimmed = name.trim();
    if (trimmed.length === 0) {
      setError("Enter a name for the key.");
      return;
    }
    setCreating(true);
    setError("");
    setSecret("");
    try {
      const created = await createApiKey(trimmed, { token });
      setSecret(created.key);
      setName("");
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not create the key.");
    } finally {
      setCreating(false);
    }
  }, [name, token, reload]);

  const onRevoke = React.useCallback(
    (key: ApiKey): void => {
      Alert.alert(
        "Revoke key",
        `Revoke "${key.name}"? Any integration using it will stop working immediately.`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Revoke",
            style: "destructive",
            onPress: () => {
              setError("");
              revokeApiKey(key.id, { token })
                .then(() => reload())
                .catch((err: unknown) => {
                  setError(
                    err instanceof Error
                      ? err.message
                      : "Could not revoke the key.",
                  );
                });
            },
          },
        ],
      );
    },
    [token, reload],
  );

  return (
    <View>
      <Text style={styles.sectionTitle}>API keys</Text>
      <View style={styles.card}>
        <Text style={styles.heading}>Create a key</Text>
        <TextInput
          style={styles.input}
          placeholder="Key name (e.g. CI pipeline)"
          placeholderTextColor={colors.muted}
          value={name}
          onChangeText={setName}
          maxLength={100}
        />
        <Pressable
          style={[styles.button, creating && styles.disabled]}
          disabled={creating}
          onPress={() => void onCreate()}
        >
          <Text style={styles.buttonText}>
            {creating ? "Creating…" : "Create key"}
          </Text>
        </Pressable>
        {secret ? (
          <View style={styles.secretBox}>
            <Text style={styles.secretLabel}>Copy now — shown once</Text>
            <Text style={styles.secret} selectable>
              {secret}
            </Text>
          </View>
        ) : null}
      </View>

      {status === "loading" ? (
        <ActivityIndicator color={colors.accent} style={styles.spacer} />
      ) : status === "error" ? (
        <Text style={styles.error}>{error}</Text>
      ) : keys.length === 0 ? (
        <Text style={styles.meta}>No API keys yet.</Text>
      ) : (
        keys.map((key) => (
          <View
            key={key.id}
            style={[styles.card, key.revoked && styles.cardDisabled]}
          >
            <Pressable
              onPress={() =>
                router.push({
                  pathname: "/account/api-keys/[id]",
                  params: { id: key.id },
                })
              }
              accessibilityRole="button"
              accessibilityLabel={`Open ${key.name || "API key"} details`}
            >
              <View style={styles.rowBetween}>
                <Text style={styles.name} numberOfLines={1}>
                  {key.name || "Untitled key"}
                </Text>
                {key.revoked ? (
                  <Text style={styles.revokedTag}>Revoked</Text>
                ) : (
                  <Icon name="chevron-forward" style={styles.chevron} />
                )}
              </View>
              <Text style={styles.mono}>{key.prefix}…</Text>
              <Text style={styles.meta}>
                {key.last_used_at
                  ? `Last used ${formatDate(key.last_used_at)}`
                  : "Never used"}
                {typeof key.usage_this_month === "number"
                  ? ` · ${key.usage_this_month.toLocaleString()} req this month`
                  : ""}
              </Text>
            </Pressable>
            {!key.revoked ? (
              <Pressable
                style={styles.revokeButton}
                onPress={() => onRevoke(key)}
                accessibilityRole="button"
                accessibilityLabel={`Revoke ${key.name}`}
              >
                <Text style={styles.revokeText}>Revoke</Text>
              </Pressable>
            ) : null}
          </View>
        ))
      )}
      {status === "ready" && error ? (
        <Text style={styles.error}>{error}</Text>
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Webhooks (per-workspace subscriptions live on their own screen)
// ---------------------------------------------------------------------------

function WebhooksLink(): React.ReactElement {
  const router = useRouter();
  return (
    <View>
      <Text style={styles.sectionTitle}>Webhooks</Text>
      <Pressable
        style={[styles.card, styles.linkRow]}
        onPress={() => router.push("/account/webhooks")}
        accessibilityRole="button"
        accessibilityLabel="Manage webhook subscriptions"
      >
        <View style={styles.flex}>
          <Text style={styles.name}>Webhook subscriptions</Text>
          <Text style={styles.meta}>
            Subscribe a workspace to job and billing events, send a signed test
            event, and inspect recent deliveries
          </Text>
        </View>
        <Icon name="chevron-forward" style={styles.chevron} />
      </Pressable>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Resale gateway keys
// ---------------------------------------------------------------------------

function GatewaySection({
  token,
  nonce,
}: {
  token: string | undefined;
  nonce: number;
}): React.ReactElement {
  const [keys, setKeys] = React.useState<readonly ProvisioningKey[]>([]);
  const [status, setStatus] = React.useState<LoadStatus>("loading");
  const [error, setError] = React.useState("");
  const [localNonce, setLocalNonce] = React.useState(0);
  const reload = React.useCallback(() => setLocalNonce((n) => n + 1), []);

  const [label, setLabel] = React.useState("");
  const [cap, setCap] = React.useState("100");
  const [markup, setMarkup] = React.useState("20");
  const [creating, setCreating] = React.useState(false);
  const [secret, setSecret] = React.useState("");

  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setStatus("loading");
    setError("");
    listKeys({ token, signal: controller.signal })
      .then((res) => {
        if (!active) return;
        setKeys(res.keys);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setError(
          err instanceof Error ? err.message : "Resale keys are unavailable.",
        );
        setStatus("error");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [token, nonce, localNonce]);

  const onCreate = React.useCallback(async (): Promise<void> => {
    const capNum = parseFloat(cap || "0");
    const markupNum = parseFloat(markup || "0");
    if (!Number.isFinite(capNum) || capNum < 0) {
      setError("Enter a valid daily cap.");
      return;
    }
    if (!Number.isFinite(markupNum) || markupNum < 0) {
      setError("Enter a valid markup percentage.");
      return;
    }
    setCreating(true);
    setError("");
    setSecret("");
    try {
      const key = await createKey(
        {
          label: label.trim(),
          daily_cap_micros: Math.round(capNum * 1_000_000),
          markup_bps: Math.round(markupNum * 100),
        },
        { token },
      );
      if (key.secret) setSecret(key.secret);
      setLabel("");
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not mint the key.");
    } finally {
      setCreating(false);
    }
  }, [label, cap, markup, token, reload]);

  return (
    <View>
      <Text style={styles.sectionTitle}>Resale gateway</Text>
      <Text style={styles.subIntro}>
        Resell generation under your own keys — set a daily cap and markup;
        billed only on success.
      </Text>
      <View style={styles.card}>
        <Text style={styles.heading}>Mint resale key</Text>
        <TextInput
          style={styles.input}
          placeholder="Label"
          placeholderTextColor={colors.muted}
          value={label}
          onChangeText={setLabel}
          maxLength={100}
        />
        <View style={styles.inlineRow}>
          <TextInput
            style={[styles.input, styles.flex, styles.noBottom]}
            placeholder="Cap USD/day"
            placeholderTextColor={colors.muted}
            keyboardType="decimal-pad"
            value={cap}
            onChangeText={setCap}
          />
          <TextInput
            style={[styles.input, styles.flex, styles.noBottom]}
            placeholder="Markup %"
            placeholderTextColor={colors.muted}
            keyboardType="decimal-pad"
            value={markup}
            onChangeText={setMarkup}
          />
        </View>
        <Pressable
          style={[styles.button, styles.spaced, creating && styles.disabled]}
          disabled={creating}
          onPress={() => void onCreate()}
        >
          <Text style={styles.buttonText}>
            {creating ? "Minting…" : "Mint key"}
          </Text>
        </Pressable>
        {secret ? (
          <View style={styles.secretBox}>
            <Text style={styles.secretLabel}>Copy now — shown once</Text>
            <Text style={styles.secret} selectable>
              {secret}
            </Text>
          </View>
        ) : null}
      </View>

      {status === "loading" ? (
        <ActivityIndicator color={colors.accent} style={styles.spacer} />
      ) : status === "error" ? (
        <Text style={styles.error}>{error}</Text>
      ) : keys.length === 0 ? (
        <Text style={styles.meta}>No resale keys yet.</Text>
      ) : (
        keys.map((key) => (
          <GatewayKeyCard
            key={key.id}
            item={key}
            token={token}
            onChanged={reload}
          />
        ))
      )}
      {status === "ready" && error ? (
        <Text style={styles.error}>{error}</Text>
      ) : null}
    </View>
  );
}

function GatewayKeyCard({
  item,
  token,
  onChanged,
}: {
  item: ProvisioningKey;
  token: string | undefined;
  onChanged: () => void;
}): React.ReactElement {
  const [base, setBase] = React.useState("1.00");
  const [quote, setQuote] = React.useState<KeyQuote | null>(null);
  const [quoting, setQuoting] = React.useState(false);
  const [error, setError] = React.useState("");

  const onQuote = React.useCallback(async (): Promise<void> => {
    const baseNum = parseFloat(base || "0");
    if (!Number.isFinite(baseNum) || baseNum < 0) {
      setError("Enter a valid base cost.");
      return;
    }
    setQuoting(true);
    setError("");
    try {
      const result = await quoteKey(
        item.id,
        { base_cost_micros: Math.round(baseNum * 1_000_000) },
        { token },
      );
      setQuote(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Quote failed.");
    } finally {
      setQuoting(false);
    }
  }, [item.id, base, token]);

  const onRevoke = React.useCallback((): void => {
    Alert.alert(
      "Revoke resale key",
      `Revoke "${item.label || item.id}"? It stops resolving immediately and cannot be restored.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Revoke",
          style: "destructive",
          onPress: () => {
            setError("");
            revokeKey(item.id, { token })
              .then(() => onChanged())
              .catch((err: unknown) => {
                setError(
                  err instanceof Error ? err.message : "Revoke failed.",
                );
              });
          },
        },
      ],
    );
  }, [item.id, item.label, token, onChanged]);

  return (
    <View style={[styles.card, item.disabled && styles.cardDisabled]}>
      <View style={styles.rowBetween}>
        <Text style={styles.name} numberOfLines={1}>
          {item.label || "Untitled key"}
        </Text>
        {item.disabled ? <Text style={styles.revokedTag}>Revoked</Text> : null}
      </View>
      <Text style={styles.meta}>
        {(item.markup_bps / 100).toFixed(1)}% markup ·{" "}
        {item.daily_cap_micros > 0
          ? `${usd(item.daily_cap_micros)}/day`
          : "unlimited"}
      </Text>

      {!item.disabled ? (
        <>
          <View style={styles.inlineRow}>
            <TextInput
              style={[styles.input, styles.flex, styles.noBottom]}
              placeholder="Base USD"
              placeholderTextColor={colors.muted}
              keyboardType="decimal-pad"
              value={base}
              onChangeText={setBase}
            />
            <Pressable
              style={[styles.smallButton, quoting && styles.disabled]}
              disabled={quoting}
              onPress={() => void onQuote()}
            >
              <Text style={styles.smallButtonText}>
                {quoting ? "…" : "Quote"}
              </Text>
            </Pressable>
          </View>
          {quote ? (
            <Text style={styles.quoteResult}>
              Charge {usd(quote.marked_up_micros)} (+{usd(quote.markup_micros)})
              · {usd(quote.daily_remaining_micros)} left today
            </Text>
          ) : null}
          <Pressable style={styles.revokeButton} onPress={onRevoke}>
            <Text style={styles.revokeText}>Revoke key</Text>
          </Pressable>
        </>
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
  subIntro: { color: colors.textSecondary, fontSize: 13, marginBottom: 12 },
  code: { color: colors.accent, fontFamily: "monospace", fontSize: 13 },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "700",
    marginTop: 20,
    marginBottom: 12,
  },
  statRow: { flexDirection: "row", gap: 12, marginBottom: 12 },
  flex: { flex: 1 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  cardDisabled: { opacity: 0.6 },
  linkRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  chevron: { color: colors.muted, fontSize: 22, fontWeight: "300" },
  heading: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "600",
    marginBottom: 10,
  },
  fieldLabel: { color: colors.muted, fontSize: 12, marginBottom: 4 },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    color: colors.textPrimary,
    padding: 10,
    marginBottom: 10,
  },
  noBottom: { marginBottom: 0 },
  inlineRow: { flexDirection: "row", gap: 8, alignItems: "center" },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    padding: 12,
    alignItems: "center",
  },
  buttonText: { color: colors.bg, fontWeight: "700" },
  spaced: { marginTop: 10 },
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
  revokedTag: { color: colors.error, fontSize: 11, fontWeight: "700" },
  meta: { color: colors.muted, fontSize: 12, marginTop: 6 },
  mono: {
    color: colors.textPrimary,
    fontSize: 13,
    fontFamily: "monospace",
    marginTop: 4,
  },
  secretBox: {
    marginTop: 10,
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
  },
  secretLabel: {
    color: colors.primary,
    fontSize: 12,
    fontWeight: "600",
    marginBottom: 4,
  },
  secret: { color: colors.textPrimary, fontSize: 12, fontFamily: "monospace" },
  smallButton: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  smallButtonText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  quoteResult: { color: colors.textSecondary, fontSize: 12, marginTop: 8 },
  revokeButton: {
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    marginTop: 10,
  },
  revokeText: { color: colors.error, fontSize: 13, fontWeight: "600" },
  disabled: { opacity: 0.5 },
  error: { color: colors.error, fontSize: 13, marginTop: 8, marginBottom: 8 },
  spacer: { height: 24 },
});
