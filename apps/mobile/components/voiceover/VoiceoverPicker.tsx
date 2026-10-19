/**
 * BRING YOUR OWN VOICEOVER (BYOV) picker for the create screen's voice section.
 *
 * The creator records their OWN narration (expo-av, via the shared
 * `useVoiceRecorder` hook) OR picks an existing audio file
 * (expo-document-picker, via `pickVoiceSampleFromFiles`). The captured audio is
 * uploaded through the shared presign flow (lib/api.ts::presignAndUpload) and the
 * returned R2 key is reported back through `onUploaded`. The parent sends that
 * key as `params.voiceover_key`, so the uploaded audio — not TTS — becomes the
 * reel's narration (the backend transcribes it with faster-whisper; §8 timing
 * single-source-of-truth is preserved).
 *
 * This component is self-contained: it owns its record/upload phase, live
 * progress, and error state, and reports only the final key (or `null` when the
 * selection is cleared / a fresh upload starts) to the parent.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { presignAndUpload, type LocalFile } from "@/lib/api";
import { pickVoiceSampleFromFiles } from "@/src/shared/media";
import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { useVoiceRecorder } from "@/components/voices/useVoiceRecorder";

type Phase = "idle" | "uploading";

interface VoiceoverPickerProps {
  token: string | undefined;
  /** The currently uploaded voiceover R2 key, or null when none is set yet. */
  voiceoverKey: string | null;
  /**
   * Reports the uploaded narration key (or null when cleared / a new upload
   * begins). The parent sends the non-null value as `params.voiceover_key`.
   */
  onUploaded: (key: string | null) => void;
  /** Disables all controls (e.g. while the parent is submitting the job). */
  disabled?: boolean;
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function VoiceoverPicker({
  token,
  voiceoverKey,
  onUploaded,
  disabled = false,
}: VoiceoverPickerProps) {
  const recorder = useVoiceRecorder();

  const [file, setFile] = useState<LocalFile | null>(null);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);

  const recording = recorder.status === "recording";
  const busy =
    disabled || phase !== "idle" || recorder.status === "stopping";

  const upload = async (picked: LocalFile | null) => {
    if (!picked) return;
    setFile(picked);
    // Clear any prior key immediately so the parent can't submit a stale one
    // while the new narration is still uploading.
    onUploaded(null);
    setProgress(0);
    setError(null);
    setPhase("uploading");
    try {
      const { key } = await presignAndUpload(picked, {
        token,
        onProgress: setProgress,
      });
      onUploaded(key);
    } catch (err) {
      setError(describeError(err, "Failed to upload the voiceover."));
    } finally {
      setPhase("idle");
    }
  };

  const onToggleRecord = async () => {
    setError(null);
    if (recording) {
      const captured = await recorder.stop();
      await upload(captured);
    } else {
      await recorder.start();
    }
  };

  const onPickFile = async () => {
    setError(null);
    try {
      await upload(await pickVoiceSampleFromFiles());
    } catch (err) {
      setError(describeError(err, "Failed to pick an audio file."));
    }
  };

  const combinedError = error ?? recorder.error;

  return (
    <View style={styles.card}>
      <Text style={styles.hint}>
        Record or upload your own narration — one speaker, no background music.
        We transcribe it for captions and use it as the reel&apos;s voiceover, so
        no TTS voice is needed.
      </Text>

      <View style={styles.row}>
        <Pressable
          style={[styles.secondary, recording && styles.recording]}
          onPress={onToggleRecord}
          disabled={busy}
        >
          <Text style={styles.secondaryText}>
            {recording ? `Stop (${formatDuration(recorder.durationMs)})` : "Record"}
          </Text>
        </Pressable>
        <Pressable
          style={styles.secondary}
          onPress={onPickFile}
          disabled={busy || recording}
        >
          <Text style={styles.secondaryText}>Upload audio</Text>
        </Pressable>
      </View>

      {file ? (
        <View style={styles.fileCard}>
          <Text style={styles.fileName} numberOfLines={1}>
            {file.name}
          </Text>
          {phase === "uploading" ? (
            <View style={styles.progressRow}>
              <View style={styles.progressTrack}>
                <View
                  style={[
                    styles.progressFill,
                    { width: `${Math.round(progress * 100)}%` },
                  ]}
                />
              </View>
              <Text style={styles.meta}>{Math.round(progress * 100)}%</Text>
            </View>
          ) : voiceoverKey ? (
            <Text style={styles.uploaded}>Uploaded</Text>
          ) : null}
        </View>
      ) : null}

      {phase === "uploading" && !file ? (
        <ActivityIndicator color={colors.primary} />
      ) : null}

      {combinedError ? <Text style={styles.error}>{combinedError}</Text> : null}
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
    gap: 10,
  },
  hint: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  row: { flexDirection: "row", gap: 10 },
  secondary: {
    flex: 1,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  recording: { backgroundColor: colors.primary, borderColor: colors.primary },
  secondaryText: { color: colors.textSecondary, fontWeight: "600" },
  fileCard: {
    backgroundColor: colors.bg,
    borderRadius: 10,
    padding: 12,
    gap: 8,
  },
  fileName: { color: colors.textPrimary, fontWeight: "600" },
  progressRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  progressTrack: {
    flex: 1,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.border,
    overflow: "hidden",
  },
  progressFill: { height: 6, backgroundColor: colors.primary },
  uploaded: { color: colors.success, fontWeight: "600" },
  meta: { color: colors.muted, fontSize: 13 },
  error: { color: colors.error, fontSize: 13 },
});
