/**
 * Capture → Import screen. Pick a screen recording / clip from the library,
 * upload it (presign → streamed PUT with progress), and get back an R2 key you
 * can drop into any template as the footage the compose stage layers under
 * (`screen_recording_key` / a split-screen `gameplay_clip`). This is the mobile
 * on-ramp for the product-demo-ad + split-screen formats.
 */

import * as React from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { router } from "expo-router";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { presignAndUpload, type LocalFile, type UploadResult } from "@/lib/api";
import { NotAVideoError, pickVideo } from "@/src/shared/media/pick-video";

type Phase = "idle" | "picked" | "uploading" | "done" | "error";

export default function ScreenImportScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [file, setFile] = React.useState<LocalFile | null>(null);
  const [progress, setProgress] = React.useState(0);
  const [result, setResult] = React.useState<UploadResult | null>(null);
  const [error, setError] = React.useState("");

  const onPick = React.useCallback(async () => {
    setError("");
    try {
      const picked = await pickVideo();
      if (!picked) return; // cancelled
      setFile(picked);
      setResult(null);
      setPhase("picked");
    } catch (err) {
      setError(err instanceof NotAVideoError || err instanceof Error ? err.message : "Could not pick a video.");
      setPhase("error");
    }
  }, []);

  const onUpload = React.useCallback(async () => {
    if (!file) return;
    setPhase("uploading");
    setProgress(0);
    setError("");
    try {
      const res = await presignAndUpload(file, { token, onProgress: setProgress });
      setResult(res);
      setPhase("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
      setPhase("error");
    }
  }, [file, token]);

  const mb = file ? (file.size / (1024 * 1024)).toFixed(1) : "0";

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Import a screen recording or clip. It uploads to your library and becomes the
        footage a template layers the avatar/captions over.
      </Text>

      <Pressable style={styles.button} onPress={onPick} disabled={phase === "uploading"}>
        <Text style={styles.buttonText}>
          {file ? "Pick a different video" : "Pick a video"}
        </Text>
      </Pressable>

      {file ? (
        <View style={styles.card}>
          <Text style={styles.name}>{file.name}</Text>
          <Text style={styles.meta}>{file.mimeType} · {mb} MB</Text>

          {phase === "uploading" ? (
            <View style={styles.progressRow}>
              <ActivityIndicator color={colors.primary} />
              <Text style={styles.meta}>Uploading… {Math.round(progress * 100)}%</Text>
            </View>
          ) : phase !== "done" ? (
            <Pressable style={[styles.button, styles.uploadBtn]} onPress={onUpload}>
              <Text style={styles.buttonText}>Upload</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      {result ? (
        <View style={styles.card}>
          <Text style={styles.badge}>Uploaded</Text>
          <Text style={styles.meta}>
            Your footage is in your library. Turn it into a reel now: Create opens
            with this clip already attached, so you only add the subject, avatar and
            voice.
          </Text>
          <Pressable
            style={[styles.button, styles.uploadBtn]}
            onPress={() =>
              router.push({
                pathname: "/(tabs)/create",
                params: {
                  recording_key: result.key,
                  recording_name: file?.name ?? "Imported footage",
                },
              })
            }
            accessibilityRole="button"
          >
            <Text style={styles.buttonText}>Make a reel with this footage</Text>
          </Pressable>
          <Pressable
            style={[styles.secondaryButton, styles.uploadBtn]}
            onPress={() => router.push("/catalog/templates")}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Browse templates first</Text>
          </Pressable>
        </View>
      ) : null}

      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  button: {
    backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 12,
    alignItems: "center", justifyContent: "center",
  },
  uploadBtn: { marginTop: 12 },
  secondaryButton: {
    borderColor: colors.border, borderWidth: 1, borderRadius: 12, paddingVertical: 12,
    alignItems: "center", justifyContent: "center",
  },
  secondaryText: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  buttonText: { color: colors.bg, fontSize: 15, fontWeight: "600" },
  card: {
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 14, marginTop: 16,
  },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "600", marginBottom: 4 },
  meta: { color: colors.muted, fontSize: 12, marginTop: 4 },
  progressRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 12 },
  badge: { color: colors.success, fontSize: 13, fontWeight: "700", marginBottom: 8 },
  error: { color: colors.error, fontSize: 14, marginTop: 12 },
  spacer: { height: 24 },
});
