/**
 * Route: /drafts — reel drafts saved on this device.
 *
 * Reachable with or without a session (the waitlist home links here), so a
 * creator can always review what they recorded for later. "Continue" opens
 * Create with the draft's brief and clip attached; without a session it first
 * sends the creator to sign in.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useFocusEffect, useRouter } from "expo-router";

import { useSession } from "@/src/shared/auth";
import {
  discardDraft,
  draftMediaAvailable,
  listDrafts,
  type ReelDraft,
} from "@/src/shared/product";
import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";

interface DraftRow {
  readonly draft: ReelDraft;
  readonly clipMissing: boolean;
}

function draftDate(ms: number): string {
  try {
    return new Date(ms).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "";
  }
}

export default function DraftsScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const [rows, setRows] = useState<DraftRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const toRows = useCallback(async (drafts: ReelDraft[]) => {
    const checked = await Promise.all(
      drafts.map(async (draft) => ({
        draft,
        clipMissing: draft.media ? !(await draftMediaAvailable(draft.media)) : false,
      })),
    );
    setRows(checked);
  }, []);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      listDrafts()
        .then((drafts) => (active ? toRows(drafts) : undefined))
        .finally(() => {
          if (active) setLoading(false);
        });
      return () => {
        active = false;
      };
    }, [toRows]),
  );

  const onDelete = async (id: string) => {
    setError(null);
    try {
      await toRows(await discardDraft(id));
    } catch {
      setError("Could not delete that draft. Please try again.");
    }
  };

  const onContinue = (id: string) => {
    if (!apiKey) {
      router.push("/");
      return;
    }
    router.push({ pathname: "/(tabs)/create", params: { draft: id } });
  };

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: "Drafts", headerShown: true }} />
      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} size="large" />
        </View>
      ) : (
        <FlatList
          contentContainerStyle={styles.content}
          data={rows}
          keyExtractor={(row) => row.draft.id}
          ListHeaderComponent={
            <View style={styles.header}>
              <Text style={styles.kicker}>DRAFTS / ON THIS DEVICE</Text>
              {!apiKey ? (
                <Text style={styles.note}>
                  Sign in to turn a draft into a reel. Drafts stay on this device
                  until you use or delete them.
                </Text>
              ) : null}
              {error ? <Text style={styles.error}>{error}</Text> : null}
            </View>
          }
          ListEmptyComponent={
            <Text style={styles.empty}>
              No drafts yet. Record or import a clip and save it as a draft to
              find it here.
            </Text>
          }
          renderItem={({ item }) => (
            <View style={styles.card}>
              <View style={styles.body}>
                <Text style={styles.title} numberOfLines={2}>
                  {item.draft.subject || "Untitled draft"}
                </Text>
                <Text style={styles.meta} numberOfLines={1}>
                  {item.draft.media
                    ? item.clipMissing
                      ? "Clip no longer on this device"
                      : item.draft.media.name
                    : "No clip attached"}
                  {"  ·  "}
                  {draftDate(item.draft.createdAt)}
                </Text>
              </View>
              <View style={styles.actions}>
                <Pressable
                  style={styles.primary}
                  onPress={() => onContinue(item.draft.id)}
                  accessibilityRole="button"
                  accessibilityLabel={`Continue draft ${item.draft.subject || item.draft.id}`}
                >
                  <Text style={styles.primaryText}>
                    {apiKey ? "Continue" : "Sign in"}
                  </Text>
                </Pressable>
                <Pressable
                  style={styles.secondary}
                  onPress={() => void onDelete(item.draft.id)}
                  accessibilityRole="button"
                  accessibilityLabel={`Delete draft ${item.draft.subject || item.draft.id}`}
                >
                  <Text style={styles.secondaryText}>Delete</Text>
                </Pressable>
              </View>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  content: { padding: spacing.xl, gap: spacing.md, flexGrow: 1 },
  header: { gap: spacing.sm, marginBottom: spacing.xs },
  kicker: { ...kicker },
  note: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 18 },
  error: { color: colors.danger, fontSize: typeScale.caption },
  empty: {
    color: colors.textFaint,
    fontSize: typeScale.body,
    textAlign: "center",
    marginTop: spacing.xxl,
  },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.md,
  },
  body: { gap: 4 },
  title: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600" },
  meta: { color: colors.textFaint, fontSize: typeScale.caption },
  actions: { flexDirection: "row", gap: spacing.sm },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  primaryText: { color: colors.onAccent, fontSize: typeScale.caption, fontWeight: "700" },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  secondaryText: { color: colors.textSecondary, fontSize: typeScale.caption, fontWeight: "600" },
});
