/**
 * Studio · Script Library
 *
 * Nav manifest: { route: "/studio/scripts", title: "Script Studio" }
 * Child routes:
 *   - { route: "/studio/scripts/generate", title: "Generate script" }
 *   - { route: "/studio/scripts/[id]",     title: "Edit script" }
 *
 * The home of the Script Studio: the creator's device-local library of scripts
 * generated from `POST /api/v1/scripts`. Lists saved scripts newest-edited-first
 * with pull-to-refresh, reloads on focus (so a just-saved script appears), opens
 * one for edit/refine, deletes one behind a confirmation dialog (optimistic
 * remove + rollback on failure), and offers a "Generate a script" entry point.
 */

import { useCallback, useState } from "react";
import {
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useFocusEffect, useRouter } from "expo-router";

import { languageLabel, scriptStatsLine } from "@/lib/scripts";
import {
  deleteSavedScript,
  listSavedScripts,
  type SavedScript,
} from "@/src/shared/product/script-library";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { Button } from "@/components/ui";

function formatEdited(iso: number): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  try {
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

export default function ScriptLibraryScreen() {
  const router = useRouter();

  const [scripts, setScripts] = useState<SavedScript[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");

  const load = useCallback(async (mode: "initial" | "refresh") => {
    if (mode === "initial") setStatus("loading");
    else setRefreshing(true);
    try {
      const data = await listSavedScripts();
      setScripts(data);
      setStatus("ready");
      setError("");
    } catch (err) {
      setError(describeError(err, "Failed to load your scripts."));
      if (mode === "initial") setStatus("error");
    } finally {
      if (mode === "refresh") setRefreshing(false);
    }
  }, []);

  // Reload on focus so a script saved in the generate/edit screens shows up.
  useFocusEffect(
    useCallback(() => {
      void load("initial");
    }, [load]),
  );

  const performDelete = useCallback(
    async (script: SavedScript) => {
      setActionError("");
      setDeletingId(script.id);
      const previous = scripts;
      setScripts((prev) => prev.filter((s) => s.id !== script.id));
      try {
        await deleteSavedScript(script.id);
      } catch (err) {
        setScripts(previous);
        setActionError(describeError(err, "Failed to delete the script."));
      } finally {
        setDeletingId(null);
      }
    },
    [scripts],
  );

  const confirmDelete = useCallback(
    (script: SavedScript) => {
      Alert.alert(
        "Delete script",
        `Delete "${script.subject}"? This removes the saved script and cannot be undone.`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Delete",
            style: "destructive",
            onPress: () => void performDelete(script),
          },
        ],
      );
    },
    [performDelete],
  );

  const keyExtractor = useCallback((s: SavedScript) => s.id, []);

  const renderItem = useCallback(
    ({ item }: { item: SavedScript }) => {
      const busy = deletingId === item.id;
      const edited = formatEdited(item.updatedAt);
      return (
        <Pressable
          style={styles.card}
          onPress={() => router.push(`/studio/scripts/${item.id}`)}
          accessibilityRole="button"
          accessibilityLabel={`Open ${item.subject}`}
        >
          <View style={styles.cardBody}>
            <Text style={styles.subject} numberOfLines={1}>
              {item.subject}
            </Text>
            <Text style={styles.preview} numberOfLines={2}>
              {item.script.trim() || "Empty script"}
            </Text>
            <View style={styles.metaRow}>
              <View style={styles.langBadge}>
                <Text style={styles.langText}>
                  {languageLabel(item.language)}
                </Text>
              </View>
              <Text style={styles.meta}>{scriptStatsLine(item.script)}</Text>
              {edited ? <Text style={styles.meta}>· {edited}</Text> : null}
            </View>
          </View>
          <Pressable
            style={styles.delete}
            onPress={() => confirmDelete(item)}
            disabled={busy}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel={`Delete ${item.subject}`}
          >
            <Text style={styles.deleteText}>{busy ? "…" : "Delete"}</Text>
          </Pressable>
        </Pressable>
      );
    },
    [deletingId, confirmDelete, router],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        Generate a narration script, refine it, then hand it straight to a reel.
        Scripts are saved on this device.
      </Text>
      <Button
        label="Generate a script"
        onPress={() => router.push("/studio/scripts/generate")}
      />
      {actionError ? (
        <Text style={styles.actionError}>{actionError}</Text>
      ) : null}
      <Text style={styles.sectionTitle}>YOUR SCRIPTS</Text>
    </View>
  );

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load("initial")}
      loadingLabel="Loading your scripts…"
    >
      <FlatList
        data={scripts}
        keyExtractor={keyExtractor}
        renderItem={renderItem}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={Separator}
        ListEmptyComponent={
          <Text style={styles.empty}>
            No saved scripts yet. Tap "Generate a script" to write your first
            narration from a subject.
          </Text>
        }
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void load("refresh")}
            tintColor={colors.accent}
          />
        }
        keyboardShouldPersistTaps="handled"
      />
    </StudioScreen>
  );
}

function Separator() {
  return <View style={styles.sep} />;
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 48 },
  header: { gap: 14, marginBottom: 12 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  sectionTitle: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
    marginTop: 4,
  },
  actionError: { color: colors.error, fontSize: 13 },
  sep: { height: 10 },
  card: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  cardBody: { flex: 1, gap: 6 },
  subject: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  preview: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  langBadge: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  langText: { color: colors.textSecondary, fontSize: 11, fontWeight: "600" },
  meta: { color: colors.muted, fontSize: 12 },
  delete: { paddingHorizontal: 8, paddingVertical: 4 },
  deleteText: { color: colors.error, fontWeight: "600", fontSize: 13 },
  empty: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
    paddingVertical: 24,
    textAlign: "center",
  },
});
