/**
 * SelfieUploader — picks a creator selfie (Photos, camera or Files) and uploads
 * it through the shared presign flow (lib/api.ts). On success it hands the
 * resulting R2 `image_key` (plus a local preview URI) up to the parent via
 * `onUploaded`; the parent turns that key into a talking-photo avatar. Mirrors
 * the Brand tab's LogoUploader; owns only its own pick/upload lifecycle + error.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { presignAndUpload, type LocalFile } from "@/lib/api";
import {
  NotAnImageError,
  captureSelfie,
  pickSelfieFromFiles,
  pickSelfieFromLibrary,
} from "@/src/shared/media";

interface SelfieUploaderProps {
  token: string | undefined;
  /** Whether a selfie has already been uploaded (drives the label). */
  hasImage: boolean;
  /** Called with the R2 key + a local preview URI after a successful upload. */
  onUploaded: (imageKey: string, previewUri: string) => void;
  disabled?: boolean;
}

export function SelfieUploader({
  token,
  hasImage,
  onUploaded,
  disabled = false,
}: SelfieUploaderProps) {
  const [progress, setProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [localUri, setLocalUri] = useState<string | null>(null);

  const busy = uploading || disabled;

  const upload = async (picked: LocalFile | null) => {
    if (!picked) return;
    setError(null);
    setProgress(0);
    setUploading(true);
    try {
      const { key } = await presignAndUpload(picked, {
        token,
        onProgress: setProgress,
      });
      setLocalUri(picked.uri);
      onUploaded(key, picked.uri);
    } catch (err) {
      setError(describeError(err, "Failed to upload the photo."));
    } finally {
      setUploading(false);
    }
  };

  const runPick = async (pick: () => Promise<LocalFile | null>) => {
    setError(null);
    try {
      await upload(await pick());
    } catch (err) {
      if (err instanceof NotAnImageError) {
        setError(err.message);
        return;
      }
      setError(describeError(err, "Failed to pick a photo."));
    }
  };

  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={styles.thumbBox}>
          {localUri ? (
            <Image
              source={{ uri: localUri }}
              style={styles.thumb}
              resizeMode="cover"
              accessibilityLabel="Selected selfie"
            />
          ) : (
            <Text style={styles.thumbEmpty}>PHOTO</Text>
          )}
        </View>

        <View style={styles.body}>
          <Text style={styles.title}>
            {hasImage ? "Photo ready" : "Choose a selfie"}
          </Text>
          <Text style={styles.hint}>
            Use a clear, well-lit, front-facing photo. We turn it into a
            talking-photo avatar that lip-syncs your reel's narration.
          </Text>
        </View>
      </View>

      {uploading ? (
        <View style={styles.progressRow}>
          <View style={styles.progressTrack}>
            <View
              style={[styles.progressFill, { width: `${Math.round(progress * 100)}%` }]}
            />
          </View>
          <Text style={styles.meta}>{Math.round(progress * 100)}%</Text>
        </View>
      ) : null}

      <View style={styles.actions}>
        <Pressable
          style={[styles.secondary, busy && styles.secondaryDisabled]}
          onPress={() => void runPick(pickSelfieFromLibrary)}
          disabled={busy}
          accessibilityRole="button"
        >
          {uploading ? (
            <ActivityIndicator color={colors.textSecondary} />
          ) : (
            <Text style={styles.secondaryText}>
              {hasImage ? "Replace" : "Photos"}
            </Text>
          )}
        </Pressable>
        <Pressable
          style={[styles.secondary, busy && styles.secondaryDisabled]}
          onPress={() => void runPick(captureSelfie)}
          disabled={busy}
          accessibilityRole="button"
        >
          <Text style={styles.secondaryText}>Camera</Text>
        </Pressable>
        <Pressable
          style={[styles.secondary, busy && styles.secondaryDisabled]}
          onPress={() => void runPick(pickSelfieFromFiles)}
          disabled={busy}
          accessibilityRole="button"
        >
          <Text style={styles.secondaryText}>Files</Text>
        </Pressable>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 12,
  },
  row: { flexDirection: "row", gap: 12, alignItems: "center" },
  thumbBox: {
    width: 56,
    height: 56,
    borderRadius: 10,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  thumb: { width: 56, height: 56 },
  thumbEmpty: { color: colors.muted, fontSize: 10, fontWeight: "700" },
  body: { flex: 1, gap: 3 },
  title: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  hint: { color: colors.muted, fontSize: 12, lineHeight: 16 },
  progressRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  progressTrack: {
    flex: 1,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.border,
    overflow: "hidden",
  },
  progressFill: { height: 6, backgroundColor: colors.primary },
  meta: { color: colors.muted, fontSize: 13 },
  actions: { flexDirection: "row", gap: 10 },
  secondary: {
    flex: 1,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  secondaryDisabled: { opacity: 0.5 },
  secondaryText: { color: colors.textSecondary, fontWeight: "600" },
  error: { color: colors.error, fontSize: 13 },
});
