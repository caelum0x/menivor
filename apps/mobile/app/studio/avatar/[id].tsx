/**
 * Studio · Avatar Detail
 *
 * Nav manifest: { route: "/studio/avatar/[id]", title: "Avatar" }
 *
 * A single avatar's detail, resolved from GET /avatars by its select-id (the
 * value sent as `params.avatar_id` when creating a reel). There is no
 * single-avatar GET endpoint, so the screen loads the catalog and finds the
 * matching entry. Shows the large thumbnail, name, provider, source, its
 * default narrator (when set), and the exact selector to use in a job, plus a
 * "Create a reel" CTA. Explicit loading / error / not-found states.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { listAvatars } from "@/lib/api";
import {
  avatarLabel,
  avatarSelectId,
  isCustomAvatar,
  type Avatar,
} from "@/lib/types";
import { toDisplayUrl } from "@/src/shared/media";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

interface DetailRow {
  label: string;
  value: string;
}

export default function StudioAvatarDetailScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const id = firstParam(params.id).trim();

  const [avatars, setAvatars] = useState<Avatar[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const data = await listAvatars({ token });
      setAvatars(data);
      setStatus("ready");
      setError("");
    } catch (err) {
      setError(describeError(err, "Failed to load the avatar."));
      setStatus("error");
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const avatar = useMemo(
    () => avatars.find((a) => avatarSelectId(a) === id) ?? null,
    [avatars, id],
  );

  const rows: DetailRow[] = useMemo(() => {
    if (!avatar) return [];
    const out: DetailRow[] = [];
    out.push({
      label: "Type",
      value: isCustomAvatar(avatar) ? "Custom talking photo" : "Provider catalog",
    });
    const provider = (avatar.provider || "").trim();
    if (provider) out.push({ label: "Provider", value: provider });
    const voice = (avatar.voice_name || "").trim();
    if (voice) out.push({ label: "Default voice", value: voice });
    out.push({ label: "Selector (avatar_id)", value: id });
    return out;
  }, [avatar, id]);

  const thumb = avatar ? toDisplayUrl(avatar.thumbnail_url) : undefined;
  const label = avatar ? avatarLabel(avatar) : "Avatar";

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load()}
      loadingLabel="Loading avatar…"
    >
      <Stack.Screen options={{ title: avatar ? label : "Avatar" }} />
      {!avatar ? (
        <View style={styles.notFound}>
          <Text style={styles.notFoundTitle}>Avatar not found</Text>
          <Text style={styles.notFoundText}>
            This avatar is no longer in your catalog. It may have been removed.
          </Text>
          <Pressable
            style={styles.secondary}
            onPress={() => router.back()}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Back to gallery</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.content}>
          <View style={styles.hero}>
            {thumb ? (
              <Image
                source={{ uri: thumb }}
                style={styles.heroImage}
                resizeMode="cover"
                accessibilityLabel={label}
              />
            ) : (
              <Text style={styles.heroEmpty}>
                {label.slice(0, 1).toUpperCase()}
              </Text>
            )}
          </View>

          <Text style={styles.title}>{label}</Text>

          <View style={styles.rows}>
            {rows.map((row) => (
              <View key={row.label} style={styles.row}>
                <Text style={styles.rowLabel}>{row.label}</Text>
                <Text style={styles.rowValue} selectable numberOfLines={2}>
                  {row.value}
                </Text>
              </View>
            ))}
          </View>

          <Pressable
            style={styles.primary}
            onPress={() => router.push("/(tabs)/create")}
            accessibilityRole="button"
          >
            <Text style={styles.primaryText}>Create a reel</Text>
          </Pressable>
        </ScrollView>
      )}
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 48, gap: 16 },
  hero: {
    aspectRatio: 1,
    borderRadius: 20,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  heroImage: { width: "100%", height: "100%" },
  heroEmpty: { color: colors.muted, fontSize: 64, fontWeight: "700" },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  rows: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: "hidden",
  },
  row: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 3,
  },
  rowLabel: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  rowValue: { color: colors.textPrimary, fontSize: 15 },
  primary: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  primaryText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  notFound: {
    flex: 1,
    padding: 24,
    gap: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  notFoundTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  notFoundText: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
  },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  secondaryText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
});
