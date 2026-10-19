/**
 * REEL PRESETS MANAGER — the caller's saved "brand kit" presets. Lists them
 * (GET /me/presets), creates new ones (POST /me/presets), duplicates and deletes
 * them (DELETE /me/presets/{id}) with optimistic list updates + rollback, and
 * APPLIES a preset by deep-linking into the Create tab with the preset config as
 * prefill params. Presets shared to a workspace show a "Shared" badge and are
 * visible to every member of that workspace. Caller-scoped via `x-api-key`.
 *
 * Nav manifest entry: { route: "/insights/presets", title: "Reel Presets" }
 */

import { useCallback, useEffect, useState } from "react";
import type { ReactElement } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useRouter } from "expo-router";

import {
  createPreset,
  deletePreset,
  isAbortError,
  listMyWorkspaces,
  listPresets,
} from "@/lib/api";
import type { Preset, PresetCreateRequest, Workspace } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

import { PresetCreateForm } from "@/components/me/PresetCreateForm";
import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";

type LoadStatus = "loading" | "ready" | "error";

/** Create-tab prefill keys a preset config can populate. */
const PREFILL_KEYS: readonly string[] = [
  "subject",
  "script",
  "layout",
  "caption_style",
  "language",
  "broll_key",
];

/** Extract create-tab prefill params from a preset config (string values only). */
function buildPrefillParams(config: Record<string, unknown>): Record<string, string> {
  const params: Record<string, string> = { prefill: "1" };
  for (const key of PREFILL_KEYS) {
    const value = config[key];
    if (typeof value === "string" && value.trim().length > 0) {
      params[key] = value;
    } else if (typeof value === "number" || typeof value === "boolean") {
      params[key] = String(value);
    }
  }
  return params;
}

export default function PresetsScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const [status, setStatus] = useState<LoadStatus>("loading");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);

  const load = useCallback(
    async (signal: AbortSignal, isRefresh: boolean): Promise<void> => {
      if (!isRefresh) setStatus("loading");
      setError("");
      try {
        const rows = await listPresets({ token, signal });
        if (signal.aborted) return;
        setPresets(rows);
        setStatus("ready");
        // Workspaces power the "Share to team" picker; a failure degrades
        // gracefully (the picker just hides) and never blocks the presets list.
        listMyWorkspaces({ token, signal })
          .then((ws) => {
            if (!signal.aborted) setWorkspaces(ws);
          })
          .catch(() => {
            /* keep presets usable even if workspaces fail */
          });
      } catch (err: unknown) {
        if (signal.aborted || isAbortError(err)) return;
        setError(describeError(err, "Failed to load your presets."));
        setStatus("error");
      } finally {
        if (!signal.aborted) setRefreshing(false);
      }
    },
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal, false);
    return () => controller.abort();
  }, [load]);

  const onRefresh = useCallback((): void => {
    setRefreshing(true);
    const controller = new AbortController();
    void load(controller.signal, true);
  }, [load]);

  const onCreate = useCallback(
    async (body: PresetCreateRequest): Promise<void> => {
      const created = await createPreset(body, { token });
      setPresets((prev) => [created, ...prev]);
    },
    [token],
  );

  const onDuplicate = useCallback(
    async (preset: Preset): Promise<void> => {
      try {
        const body: PresetCreateRequest = {
          name: `${preset.name} copy`,
          config: preset.config ?? {},
          ...(preset.workspace_id ? { workspace_id: preset.workspace_id } : {}),
        };
        const created = await createPreset(body, { token });
        setPresets((prev) => [created, ...prev]);
      } catch (err: unknown) {
        Alert.alert("Couldn't duplicate", describeError(err, "Please try again."));
      }
    },
    [token],
  );

  const onDelete = useCallback(
    async (preset: Preset): Promise<void> => {
      const previous = presets;
      setPresets((prev) => prev.filter((p) => p.id !== preset.id));
      try {
        await deletePreset(preset.id, { token });
      } catch (err: unknown) {
        setPresets(previous);
        Alert.alert("Couldn't delete", describeError(err, "Please try again."));
      }
    },
    [presets, token],
  );

  const confirmDelete = useCallback(
    (preset: Preset): void => {
      Alert.alert(
        "Delete preset",
        `Delete "${preset.name}"? This can't be undone.`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Delete",
            style: "destructive",
            onPress: () => {
              void onDelete(preset);
            },
          },
        ],
      );
    },
    [onDelete],
  );

  const onApply = useCallback(
    (preset: Preset): void => {
      const params = buildPrefillParams(preset.config ?? {});
      router.push({ pathname: "/(tabs)/create", params });
    },
    [router],
  );

  return (
    <>
      <Stack.Screen options={{ title: "Reel Presets", presentation: "card" }} />
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
        <Text style={styles.pageTitle}>Reel presets</Text>
        <Text style={styles.pageSub}>
          Save a favourite subject / script / layout combo and apply it to a new
          reel in one tap.
        </Text>

        <View style={styles.formBlock}>
          <PresetCreateForm onCreate={onCreate} workspaces={workspaces} />
        </View>

        {status === "loading" ? (
          <View style={styles.center}>
            <ActivityIndicator color={colors.accent} size="large" />
          </View>
        ) : status === "error" ? (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{error}</Text>
            <Pressable style={styles.retry} onPress={onRefresh}>
              <Text style={styles.retryText}>Try again</Text>
            </Pressable>
          </View>
        ) : presets.length === 0 ? (
          <Text style={styles.empty}>
            No presets yet. Save a favourite avatar / voice / layout combo above
            to reuse it on every new reel.
          </Text>
        ) : (
          <View style={styles.list}>
            {presets.map((preset) => (
              <PresetRow
                key={preset.id}
                preset={preset}
                onApply={onApply}
                onDuplicate={onDuplicate}
                onDelete={confirmDelete}
              />
            ))}
          </View>
        )}

        <View style={styles.spacer} />
      </ScrollView>
    </>
  );
}

interface PresetRowProps {
  preset: Preset;
  onApply: (preset: Preset) => void;
  onDuplicate: (preset: Preset) => Promise<void>;
  onDelete: (preset: Preset) => void;
}

function PresetRow({ preset, onApply, onDuplicate, onDelete }: PresetRowProps): ReactElement {
  const [expanded, setExpanded] = useState(false);
  const [duplicating, setDuplicating] = useState(false);

  const config = preset.config ?? {};
  const configKeys = Object.keys(config);
  const summary =
    configKeys.length > 0
      ? `${configKeys.length} setting${configKeys.length === 1 ? "" : "s"}: ${configKeys
          .slice(0, 4)
          .join(", ")}`
      : "No settings saved";
  const isShared = preset.shared === true || !!preset.workspace_id;

  const onDuplicatePress = useCallback(async (): Promise<void> => {
    setDuplicating(true);
    try {
      await onDuplicate(preset);
    } finally {
      setDuplicating(false);
    }
  }, [onDuplicate, preset]);

  return (
    <View style={styles.card}>
      <Pressable
        style={styles.cardHead}
        onPress={() => setExpanded((prev) => !prev)}
      >
        <View style={styles.cardBody}>
          <View style={styles.nameRow}>
            <Text style={styles.name} numberOfLines={1}>
              {preset.name}
            </Text>
            {isShared ? (
              <View style={styles.badge} accessibilityLabel="Shared to team">
                <Text style={styles.badgeText}>Shared</Text>
              </View>
            ) : null}
          </View>
          <Text style={styles.summary} numberOfLines={2}>
            {summary}
          </Text>
        </View>
        <Text style={styles.chevron}>{expanded ? "Hide" : "View"}</Text>
      </Pressable>

      {expanded && configKeys.length > 0 ? (
        <View style={styles.configBox}>
          {configKeys.map((key) => (
            <View key={key} style={styles.configRow}>
              <Text style={styles.configKey}>{key}</Text>
              <Text style={styles.configValue} numberOfLines={2}>
                {formatConfigValue(config[key])}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      <View style={styles.actions}>
        <Pressable style={styles.applyBtn} onPress={() => onApply(preset)}>
          <Text style={styles.applyText}>Apply to new reel</Text>
        </Pressable>
        <Pressable
          style={styles.ghostBtn}
          onPress={onDuplicatePress}
          disabled={duplicating}
        >
          {duplicating ? (
            <ActivityIndicator color={colors.textSecondary} size="small" />
          ) : (
            <Text style={styles.ghostText}>Duplicate</Text>
          )}
        </Pressable>
        <Pressable style={styles.ghostBtn} onPress={() => onDelete(preset)}>
          <Text style={styles.deleteText}>Delete</Text>
        </Pressable>
      </View>
    </View>
  );
}

/** Render a config value compactly for the detail list. */
function formatConfigValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20 },
  pageTitle: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  pageSub: { color: colors.muted, fontSize: 13, lineHeight: 18, marginTop: 4 },
  formBlock: { marginTop: 16, marginBottom: 20 },
  list: { gap: 12 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 12,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 12 },
  cardBody: { flex: 1, gap: 4 },
  nameRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "700", flexShrink: 1 },
  badge: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  badgeText: {
    color: colors.accent,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
  summary: { color: colors.muted, fontSize: 12 },
  chevron: { color: colors.accent, fontSize: 13, fontWeight: "700" },
  configBox: {
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    gap: 8,
  },
  configRow: { flexDirection: "row", gap: 12 },
  configKey: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    width: 110,
  },
  configValue: { flex: 1, color: colors.textSecondary, fontSize: 12 },
  actions: { flexDirection: "row", alignItems: "center", gap: 8 },
  applyBtn: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 11,
    alignItems: "center",
  },
  applyText: { color: colors.bg, fontWeight: "800", fontSize: 14 },
  ghostBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 11,
    alignItems: "center",
    justifyContent: "center",
    minWidth: 84,
  },
  ghostText: { color: colors.textSecondary, fontWeight: "700", fontSize: 14 },
  deleteText: { color: colors.error, fontWeight: "700", fontSize: 14 },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 60 },
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
  spacer: { height: 40 },
});
