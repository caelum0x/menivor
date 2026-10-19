/**
 * Gateway screen — mint + manage API-resale provisioning keys on mobile.
 * The key secret is shown exactly once, right after minting.
 */

import * as React from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import {
  createKey,
  listKeys,
  quoteKey,
  revokeKey,
  usd,
  type KeyQuote,
  type ProvisioningKey,
} from "@/lib/gateway";

export default function GatewayScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [keys, setKeys] = React.useState<ProvisioningKey[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [label, setLabel] = React.useState("");
  const [cap, setCap] = React.useState("100");
  const [markup, setMarkup] = React.useState("20");
  const [secret, setSecret] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const res = await listKeys({ token });
      setKeys(res.keys);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const onCreate = React.useCallback(async () => {
    setBusy(true);
    setError("");
    setSecret("");
    try {
      const key = await createKey(
        {
          label: label.trim(),
          daily_cap_micros: Math.round(parseFloat(cap || "0") * 1_000_000),
          markup_bps: Math.round(parseFloat(markup || "0") * 100),
        },
        { token },
      );
      if (key.secret) setSecret(key.secret);
      setLabel("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to mint.");
    } finally {
      setBusy(false);
    }
  }, [label, cap, markup, token, load]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Resell generation under your own keys — set a daily cap and markup; billed only on success.
      </Text>

      <View style={styles.card}>
        <Text style={styles.heading}>Mint key</Text>
        <TextInput
          style={styles.input}
          placeholder="Label"
          placeholderTextColor={colors.muted}
          value={label}
          onChangeText={setLabel}
        />
        <View style={styles.row}>
          <TextInput
            style={[styles.input, styles.flex]}
            placeholder="Cap USD"
            placeholderTextColor={colors.muted}
            keyboardType="decimal-pad"
            value={cap}
            onChangeText={setCap}
          />
          <TextInput
            style={[styles.input, styles.flex]}
            placeholder="Markup %"
            placeholderTextColor={colors.muted}
            keyboardType="decimal-pad"
            value={markup}
            onChangeText={setMarkup}
          />
        </View>
        <Pressable style={styles.button} disabled={busy} onPress={() => void onCreate()}>
          <Text style={styles.buttonText}>{busy ? "Minting…" : "Mint key"}</Text>
        </Pressable>
        {secret ? (
          <View style={styles.secretBox}>
            <Text style={styles.secretLabel}>Copy now — shown once</Text>
            <Text style={styles.secret}>{secret}</Text>
          </View>
        ) : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} style={styles.spacer} />
      ) : keys.length === 0 ? (
        <Text style={styles.meta}>No keys yet — mint one above to start reselling.</Text>
      ) : (
        keys.map((k) => (
          <KeyCard key={k.id} apiKey={k} token={token} onChanged={load} />
        ))
      )}
      <View style={styles.spacer} />
    </ScrollView>
  );
}

function KeyCard({
  apiKey,
  token,
  onChanged,
}: {
  apiKey: ProvisioningKey;
  token: string | undefined;
  onChanged: () => Promise<void> | void;
}) {
  const [base, setBase] = React.useState("1.00");
  const [quote, setQuote] = React.useState<KeyQuote | null>(null);
  const [quoting, setQuoting] = React.useState(false);
  const [revoking, setRevoking] = React.useState(false);
  const [error, setError] = React.useState("");

  const onQuote = React.useCallback(async () => {
    setQuoting(true);
    setError("");
    try {
      const result = await quoteKey(
        apiKey.id,
        { base_cost_micros: Math.round(parseFloat(base || "0") * 1_000_000) },
        { token },
      );
      setQuote(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Quote failed.");
    } finally {
      setQuoting(false);
    }
  }, [apiKey.id, base, token]);

  const onRevoke = React.useCallback(async () => {
    setRevoking(true);
    setError("");
    try {
      await revokeKey(apiKey.id, { token });
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revoke failed.");
      setRevoking(false);
    }
  }, [apiKey.id, token, onChanged]);

  return (
    <View style={[styles.card, apiKey.disabled && styles.cardDisabled]}>
      <View style={styles.keyHeader}>
        <Text style={styles.name}>{apiKey.label || "Untitled key"}</Text>
        {apiKey.disabled ? <Text style={styles.revokedTag}>Revoked</Text> : null}
      </View>
      <Text style={styles.meta}>
        {(apiKey.markup_bps / 100).toFixed(1)}% markup ·{" "}
        {apiKey.daily_cap_micros > 0 ? `${usd(apiKey.daily_cap_micros)}/day` : "unlimited"}
      </Text>

      {!apiKey.disabled ? (
        <>
          <View style={styles.quoteRow}>
            <TextInput
              style={[styles.input, styles.quoteInput]}
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
              <Text style={styles.smallButtonText}>{quoting ? "…" : "Quote"}</Text>
            </Pressable>
          </View>
          {quote ? (
            <Text style={styles.quoteResult}>
              Charge {usd(quote.marked_up_micros)} (+{usd(quote.markup_micros)}) ·{" "}
              {usd(quote.daily_remaining_micros)} left today
            </Text>
          ) : null}
          <Pressable
            style={[styles.revokeButton, revoking && styles.disabled]}
            disabled={revoking}
            onPress={() => void onRevoke()}
            accessibilityRole="button"
            accessibilityLabel={`Revoke key ${apiKey.label || apiKey.id}`}
          >
            <Text style={styles.revokeText}>{revoking ? "Revoking…" : "Revoke key"}</Text>
          </Pressable>
        </>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  heading: { color: colors.textPrimary, fontSize: 15, fontWeight: "600", marginBottom: 8 },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    color: colors.textPrimary,
    padding: 10,
    marginBottom: 8,
  },
  row: { flexDirection: "row", gap: 8 },
  flex: { flex: 1 },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    padding: 12,
    alignItems: "center",
  },
  buttonText: { color: "#fff", fontWeight: "600" },
  secretBox: {
    marginTop: 10,
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
  },
  secretLabel: { color: colors.primary, fontSize: 12, fontWeight: "600", marginBottom: 4 },
  secret: { color: colors.textPrimary, fontSize: 12, fontFamily: "Courier" },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "600", marginBottom: 4 },
  meta: { color: colors.muted, fontSize: 12 },
  error: { color: colors.error, fontSize: 13, marginTop: 8 },
  spacer: { height: 24 },
  cardDisabled: { opacity: 0.6 },
  keyHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  revokedTag: { color: colors.error, fontSize: 11, fontWeight: "700" },
  quoteRow: { flexDirection: "row", gap: 8, marginTop: 10, alignItems: "center" },
  quoteInput: { flex: 1, marginBottom: 0 },
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
  disabled: { opacity: 0.5 },
  revokeButton: {
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    marginTop: 10,
  },
  revokeText: { color: colors.error, fontSize: 13, fontWeight: "600" },
});
