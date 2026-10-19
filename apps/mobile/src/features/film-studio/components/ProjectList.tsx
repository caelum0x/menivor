/**
 * The caller's saved film projects (`GET /film/projects`, newest first). Tap to
 * reopen a project's shots/render/export view; long-press to rename or delete.
 * The "New film" action opens the plan form.
 */

import * as React from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useFocusEffect } from "expo-router";

import { colors } from "@/components/me/theme";
import { Icon } from "@/components/ui/Icon";
import { ApiError } from "@/src/shared/api";
import {
  deleteFilmProject,
  listFilmProjects,
  renameFilmProject,
  type FilmProjectListItem,
} from "@/lib/film";

interface ProjectListProps {
  token: string | undefined;
  onOpen: (projectId: string) => void;
  onNew: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  planned: "Planned",
  rendering: "Rendering shots",
  shots_ready: "Ready to export",
  assembled: "Ready to export",
  exporting: "Exporting",
  exported: "Exported",
  failed: "Failed",
};

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 503) return "Film persistence is unavailable right now.";
    return err.message;
  }
  return err instanceof Error ? err.message : fallback;
}

export function ProjectList({ token, onOpen, onNew }: ProjectListProps) {
  const [projects, setProjects] = React.useState<FilmProjectListItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [renaming, setRenaming] = React.useState<FilmProjectListItem | null>(null);
  const [draftTitle, setDraftTitle] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setProjects(await listFilmProjects({ token }));
    } catch (err) {
      setError(describe(err, "Could not load your films."));
    }
  }, [token]);

  useFocusEffect(
    React.useCallback(() => {
      let active = true;
      load().finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
      };
    }, [load]),
  );

  const onRefresh = React.useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const onManage = React.useCallback(
    (project: FilmProjectListItem) => {
      Alert.alert(project.title || "Untitled film", undefined, [
        {
          text: "Rename",
          onPress: () => {
            setRenaming(project);
            setDraftTitle(project.title);
          },
        },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => {
            deleteFilmProject(project.id, { token })
              .then(() => setProjects((prev) => prev.filter((p) => p.id !== project.id)))
              .catch((err) => setError(describe(err, "Could not delete the film.")));
          },
        },
        { text: "Cancel", style: "cancel" },
      ]);
    },
    [token],
  );

  const onSaveTitle = React.useCallback(async () => {
    if (!renaming || !draftTitle.trim() || saving) return;
    setSaving(true);
    try {
      const updated = await renameFilmProject(renaming.id, draftTitle, { token });
      setProjects((prev) =>
        prev.map((p) => (p.id === renaming.id ? { ...p, title: updated.title ?? draftTitle.trim() } : p)),
      );
      setRenaming(null);
    } catch (err) {
      setError(describe(err, "Could not rename the film."));
    } finally {
      setSaving(false);
    }
  }, [draftTitle, renaming, saving, token]);

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={projects}
      keyExtractor={(p) => p.id}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
      }
      ListHeaderComponent={
        <View style={styles.header}>
          <Text style={styles.intro}>
            Plan an identity-locked multi-shot film, render every shot, then export one stitched video.
          </Text>
          <Pressable style={styles.newButton} onPress={onNew} accessibilityRole="button">
            <Icon name="add" size={18} color={colors.bg} />
            <Text style={styles.newText}>New film</Text>
          </Pressable>
          {renaming ? (
            <View style={styles.renameBox}>
              <Text style={styles.label}>Rename film</Text>
              <TextInput
                style={styles.input}
                value={draftTitle}
                onChangeText={setDraftTitle}
                maxLength={200}
                autoFocus
                placeholderTextColor={colors.muted}
              />
              <View style={styles.renameActions}>
                <Text style={styles.link} onPress={() => setRenaming(null)}>
                  Cancel
                </Text>
                <Text
                  style={[styles.link, (!draftTitle.trim() || saving) && styles.disabled]}
                  onPress={() => void onSaveTitle()}
                >
                  {saving ? "Saving" : "Save"}
                </Text>
              </View>
            </View>
          ) : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          {projects.length > 0 ? <Text style={styles.section}>Your films</Text> : null}
        </View>
      }
      ListEmptyComponent={
        error ? null : <Text style={styles.empty}>No films yet. Start one with New film.</Text>
      }
      renderItem={({ item }) => (
        <Pressable
          style={styles.card}
          onPress={() => onOpen(item.id)}
          onLongPress={() => onManage(item)}
          accessibilityRole="button"
          accessibilityLabel={`Open film ${item.title || item.id}`}
          accessibilityHint="Long-press to rename or delete"
        >
          <View style={styles.cardBody}>
            <Text style={styles.name} numberOfLines={1}>
              {item.title || "Untitled film"}
            </Text>
            <Text style={styles.meta}>
              {STATUS_LABEL[item.status] ?? item.status} · {item.shot_count} shots ·{" "}
              {Number(item.total_runtime_s || 0).toFixed(0)}s
            </Text>
          </View>
          <Pressable onPress={() => onManage(item)} hitSlop={10} accessibilityLabel="Manage film">
            <Icon name="ellipsis-horizontal" size={18} color={colors.muted} />
          </Pressable>
        </Pressable>
      )}
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, gap: 10 },
  centered: { flex: 1, backgroundColor: colors.bg, alignItems: "center", justifyContent: "center" },
  header: { gap: 12, marginBottom: 4 },
  intro: { color: colors.textSecondary, fontSize: 14 },
  newButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
  },
  newText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  renameBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 8,
  },
  label: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  input: {
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    color: colors.textPrimary,
    padding: 10,
  },
  renameActions: { flexDirection: "row", justifyContent: "flex-end", gap: 20 },
  link: { color: colors.primary, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  section: { color: colors.textSecondary, fontSize: 12, fontWeight: "700", textTransform: "uppercase", marginTop: 8 },
  error: { color: colors.error, fontSize: 13 },
  empty: { color: colors.muted, fontSize: 14, textAlign: "center", marginTop: 24 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  cardBody: { flex: 1, gap: 4 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  meta: { color: colors.muted, fontSize: 12 },
});
