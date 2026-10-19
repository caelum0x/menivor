/**
 * LogoUploader — picks a transparent PNG logo (media library or Files) and
 * uploads it through the shared presign flow (lib/api.ts). On success it hands
 * the resulting R2 `logo_key` (plus a local preview URI) up to the parent via
 * `onUploaded`; the parent persists the key with the rest of the brand settings.
 * A "Remove logo" action clears the watermark (empty key) via `onRemove`.
 *
 * Owns only its own pick/upload lifecycle + error; the current logo state lives
 * in the parent so it stays in sync with the position/opacity/enabled form.
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
import { toDisplayUrl } from "@/src/shared/media";
import {
  NotPngError,
  pickLogoFromFiles,
  pickLogoFromLibrary,
} from "@/src/shared/media";

interface LogoUploaderProps {
  token: string | undefined;
  /** Presigned URL of the currently-saved logo (for the thumbnail), if any. */
  currentLogoUrl?: string | null;
  /** Whether a logo is currently set (drives the Remove affordance). */
  hasLogo: boolean;
  /** Called with the new R2 key + a local preview URI after a successful upload. */
  onUploaded: (logoKey: string, previewUri: string) => void;
  /** Called to clear the logo (sets an empty key on the next save). */
  onRemove: () => void;
  disabled?: boolean;
}

export function LogoUploader({
  token,
  currentLogoUrl,
  hasLogo,
  onUploaded,
  onRemove,
  disabled = false,
}: LogoUploaderProps) {
  const [progress, setProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Local preview of the just-picked file, before the saved logo_url refreshes.
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
      setError(describeError(err, "Failed to upload the logo."));
    } finally {
      setUploading(false);
    }
  };

  const runPick = async (pick: () => Promise<LocalFile | null>) => {
    setError(null);
    try {
      await upload(await pick());
    } catch (err) {
      if (err instanceof NotPngError) {
        setError(err.message);
        return;
      }
      setError(describeError(err, "Failed to pick a logo."));
    }
  };

  const previewUri = localUri ?? toDisplayUrl(currentLogoUrl);

  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={styles.thumbBox}>
          {previewUri ? (
            <Image
              source={{ uri: previewUri }}
              style={styles.thumb}
              resizeMode="contain"
              accessibilityLabel="Current logo"
            />
          ) : (
            <Text style={styles.thumbEmpty}>PNG</Text>
          )}
        </View>

        <View style={styles.body}>
          <Text style={styles.title}>
            {hasLogo ? "Logo uploaded" : "No logo yet"}
          </Text>
          <Text style={styles.hint}>
            Upload a transparent PNG. It is overlaid on every reel at the corner
            and opacity below.
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
          onPress={() => void runPick(pickLogoFromLibrary)}
          disabled={busy}
          accessibilityRole="button"
        >
          {uploading ? (
            <ActivityIndicator color={colors.textSecondary} />
          ) : (
            <Text style={styles.secondaryText}>
              {hasLogo ? "Replace" : "Choose from Photos"}
            </Text>
          )}
        </Pressable>
        <Pressable
          style={[styles.secondary, busy && styles.secondaryDisabled]}
          onPress={() => void runPick(pickLogoFromFiles)}
          disabled={busy}
          accessibilityRole="button"
        >
          <Text style={styles.secondaryText}>Files</Text>
        </Pressable>
      </View>

      {hasLogo ? (
        <Pressable
          onPress={onRemove}
          disabled={busy}
          accessibilityRole="button"
          style={styles.removeBtn}
        >
          <Text style={[styles.removeText, busy && styles.removeDisabled]}>
            Remove logo
          </Text>
        </Pressable>
      ) : null}

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
  thumb: { width: 48, height: 48 },
  thumbEmpty: { color: colors.muted, fontSize: 11, fontWeight: "700" },
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
  removeBtn: { alignSelf: "flex-start" },
  removeText: { color: colors.error, fontSize: 13, fontWeight: "600" },
  removeDisabled: { opacity: 0.5 },
  error: { color: colors.error, fontSize: 13 },
});
