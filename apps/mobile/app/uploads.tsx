/**
 * Route: /uploads — every source clip, image and audio file the creator
 * uploaded (GET /uploads). Tap a row to preview it inline, reuse a video as the
 * screen recording for a new reel, or delete it (DELETE /uploads/{id}).
 * Pull-to-refresh, refresh-on-focus, and loading / error / empty states.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useFocusEffect, useRouter } from "expo-router";

import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { JobVideo } from "@/src/shared/media";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";
import { Icon, type IconName } from "@/components/ui/Icon";
import {
  deleteUpload,
  formatBytes,
  listUploads,
  uploadMediaKind,
  type UploadItem,
  type UploadMediaKind,
} from "@/lib/uploads";

const KIND_ICON: Record<UploadMediaKind, IconName> = {
  video: "videocam-outline",
  image: "image-outline",
  audio: "musical-notes-outline",
  other: "document-outline",
};

function uploadDate(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 503) return "Upload storage is unavailable right now.";
    return err.message;
  }
  return err instanceof Error ? err.message : fallback;
}

export default function UploadsScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [items, setItems] = useState<UploadItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setItems(await listUploads({ token }));
    } catch (err) {
      setError(describe(err, "Failed to load uploads."));
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      load().finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const onDelete = useCallback(
    (item: UploadItem) => {
      Alert.alert("Delete upload?", `${item.filename} will be removed from your storage.`, [
        { text: "Keep", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => {
            setDeletingId(item.id);
            deleteUpload(item.id, { token })
              .then(() => {
                setItems((prev) => prev.filter((row) => row.id !== item.id));
                setOpenId((prev) => (prev === item.id ? null : prev));
              })
              .catch((err) => setError(describe(err, "Could not delete the upload.")))
              .finally(() => setDeletingId(null));
          },
        },
      ]);
    },
    [token],
  );

  const onUseInCreate = useCallback(
    (item: UploadItem) => {
      router.push({
        pathname: "/(tabs)/create",
        params: { recording_key: item.key, recording_name: item.filename },
      });
    },
    [router],
  );

  if (loading) {
    return (
      <View style={[styles.container, styles.center]}>
        <Stack.Screen options={{ title: "Uploads" }} />
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: "Uploads" }} />
      <FlatList
        contentContainerStyle={styles.content}
        data={items}
        keyExtractor={(item) => item.id}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
        ListHeaderComponent={
          <View style={styles.header}>
            <Text style={styles.intro}>
              Source media you uploaded. Reuse a clip as the recording for a new reel.
            </Text>
            <Pressable
              style={styles.uploadNew}
              onPress={() => router.push("/capture")}
              accessibilityRole="button"
              accessibilityLabel="Upload or record new footage"
            >
              <Icon name="add" size={18} color={colors.onAccent} />
              <Text style={styles.uploadNewText}>Upload new</Text>
            </Pressable>
            {error ? <Text style={styles.error}>{error}</Text> : null}
          </View>
        }
        ListEmptyComponent={
          error ? null : (
            <View style={styles.center}>
              <Icon name="cloud-upload-outline" size={36} color={colors.textFaint} />
              <Text style={styles.empty}>
                No uploads yet. Footage you import in Capture or Create shows up here.
              </Text>
            </View>
          )
        }
        renderItem={({ item }) => {
          const kind = uploadMediaKind(item);
          const open = openId === item.id;
          const meta = [formatBytes(item.sizeBytes), uploadDate(item.createdAt)]
            .filter(Boolean)
            .join("  ·  ");
          return (
            <View style={styles.card}>
              <Pressable
                style={styles.row}
                onPress={() => setOpenId(open ? null : item.id)}
                accessibilityRole="button"
                accessibilityLabel={`${open ? "Hide" : "Preview"} ${item.filename}`}
              >
                <Icon name={KIND_ICON[kind]} size={22} color={colors.textSecondary} />
                <View style={styles.rowBody}>
                  <Text style={styles.name} numberOfLines={1}>
                    {item.filename}
                  </Text>
                  {meta ? <Text style={styles.meta}>{meta}</Text> : null}
                </View>
                <Icon
                  name={open ? "chevron-up" : "chevron-down"}
                  size={18}
                  color={colors.textFaint}
                />
              </Pressable>

              {open ? (
                <View style={styles.preview}>
                  {!item.url ? (
                    <Text style={styles.meta}>No preview link is available for this file.</Text>
                  ) : kind === "video" ? (
                    <JobVideo uri={item.url} />
                  ) : kind === "image" ? (
                    <Image source={{ uri: item.url }} style={styles.image} resizeMode="contain" />
                  ) : (
                    <Text style={styles.meta}>Preview is not supported for this file type.</Text>
                  )}
                  <View style={styles.actions}>
                    {kind === "video" && item.key ? (
                      <Pressable
                        style={styles.primary}
                        onPress={() => onUseInCreate(item)}
                        accessibilityRole="button"
                        accessibilityLabel={`Create a reel from ${item.filename}`}
                      >
                        <Icon name="sparkles-outline" size={16} color={colors.onAccent} />
                        <Text style={styles.primaryText}>Use in Create</Text>
                      </Pressable>
                    ) : null}
                    {item.jobId ? (
                      <Pressable
                        style={styles.secondary}
                        onPress={() => router.push(`/job/${item.jobId}`)}
                        accessibilityRole="button"
                        accessibilityLabel="Open the reel made from this upload"
                      >
                        <Text style={styles.secondaryText}>Open reel</Text>
                      </Pressable>
                    ) : null}
                    <Pressable
                      style={[styles.secondary, deletingId === item.id && styles.disabled]}
                      onPress={() => onDelete(item)}
                      disabled={deletingId === item.id}
                      accessibilityRole="button"
                      accessibilityLabel={`Delete ${item.filename}`}
                    >
                      {deletingId === item.id ? (
                        <ActivityIndicator color={colors.danger} />
                      ) : (
                        <Text style={styles.deleteText}>Delete</Text>
                      )}
                    </Pressable>
                  </View>
                </View>
              ) : null}
            </View>
          );
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.xl, gap: spacing.md, flexGrow: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", paddingTop: 60, gap: spacing.md },
  header: { gap: spacing.md, marginBottom: spacing.xs },
  intro: { color: colors.textSecondary, fontSize: typeScale.body },
  uploadNew: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: spacing.xs,
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  uploadNewText: { color: colors.onAccent, fontWeight: "700" },
  empty: { color: colors.textFaint, fontSize: typeScale.body, textAlign: "center", paddingHorizontal: spacing.xl },
  error: { color: colors.danger, fontSize: typeScale.caption },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.md,
  },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  rowBody: { flex: 1, gap: 2 },
  name: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600" },
  meta: { color: colors.textFaint, fontSize: typeScale.micro },
  preview: { gap: spacing.md },
  image: { width: "100%", aspectRatio: 1, borderRadius: radius.md, backgroundColor: colors.surfaceMuted },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  primary: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  primaryText: { color: colors.onAccent, fontWeight: "700", fontSize: typeScale.caption },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minWidth: 72,
    alignItems: "center",
  },
  secondaryText: { color: colors.textSecondary, fontWeight: "600", fontSize: typeScale.caption },
  deleteText: { color: colors.danger, fontWeight: "600", fontSize: typeScale.caption },
  disabled: { opacity: 0.5 },
});
