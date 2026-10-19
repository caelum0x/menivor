/**
 * Capture + submit form for a new brand voice. The creator records a 30–60s
 * sample (expo-av) OR picks an existing audio file (expo-document-picker); the
 * sample is uploaded through the shared presign flow (lib/api.ts) and the
 * returned R2 key is cloned via `onClone`.
 *
 * CONSENT is mandatory: submit stays disabled until the creator flips the
 * attestation switch confirming they own or are authorized to use the voice.
 * The parent owns the actual `cloneVoice` call + list insertion.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";

import { presignAndUpload, type LocalFile } from "@/lib/api";
import type { CloneVoiceRequest } from "@/lib/types";
import { pickVoiceSampleFromFiles } from "@/src/shared/media";
import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";

import { useVoiceRecorder } from "./useVoiceRecorder";

type Phase = "idle" | "uploading" | "submitting";

/** Recommended sample-length window, surfaced as guidance to the creator. */
const MIN_SAMPLE_S = 30;
const MAX_SAMPLE_S = 60;

interface VoiceRecorderProps {
  token: string | undefined;
  /** Performs the clone; resolves once the new voice is in the list. */
  onClone: (body: CloneVoiceRequest) => Promise<void>;
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function VoiceRecorder({ token, onClone }: VoiceRecorderProps) {
  const recorder = useVoiceRecorder();

  const [name, setName] = useState("");
  const [consent, setConsent] = useState(false);
  const [file, setFile] = useState<LocalFile | null>(null);
  const [sampleKey, setSampleKey] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);

  const busy = phase !== "idle" || recorder.status === "stopping";

  const upload = async (picked: LocalFile | null) => {
    if (!picked) return;
    setFile(picked);
    setSampleKey(null);
    setProgress(0);
    setError(null);
    setPhase("uploading");
    try {
      const { key } = await presignAndUpload(picked, {
        token,
        onProgress: setProgress,
      });
      setSampleKey(key);
    } catch (err) {
      setError(describeError(err, "Failed to upload the voice sample."));
    } finally {
      setPhase("idle");
    }
  };

  const onToggleRecord = async () => {
    setError(null);
    if (recorder.status === "recording") {
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

  const canSubmit =
    !!name.trim() &&
    !!sampleKey &&
    consent &&
    phase === "idle" &&
    recorder.status === "idle";

  const onSubmit = async () => {
    if (!sampleKey || !consent) return;
    setPhase("submitting");
    setError(null);
    try {
      await onClone({
        name: name.trim(),
        sample_key: sampleKey,
        consent: true,
      });
      // Reset for the next clone.
      setName("");
      setConsent(false);
      setFile(null);
      setSampleKey(null);
      setProgress(0);
    } catch (err) {
      setError(describeError(err, "Failed to clone the voice."));
    } finally {
      setPhase("idle");
    }
  };

  const recording = recorder.status === "recording";
  const combinedError = error ?? recorder.error;

  return (
    <View style={styles.card}>
      <Text style={styles.label}>New brand voice</Text>

      <TextInput
        style={styles.input}
        value={name}
        onChangeText={setName}
        placeholder="Voice name (e.g. My narrator)"
        placeholderTextColor={colors.muted}
        editable={!busy}
        maxLength={200}
      />

      <Text style={styles.hint}>
        Record or upload a clean {MIN_SAMPLE_S}–{MAX_SAMPLE_S}s sample of the
        voice — one speaker, no background music.
      </Text>

      <View style={styles.row}>
        <Pressable
          style={[styles.secondary, recording && styles.recording]}
          onPress={onToggleRecord}
          disabled={busy}
        >
          <Text style={styles.secondaryText}>
            {recording
              ? `Stop (${formatDuration(recorder.durationMs)})`
              : "Record"}
          </Text>
        </Pressable>
        <Pressable
          style={styles.secondary}
          onPress={onPickFile}
          disabled={busy || recording}
        >
          <Text style={styles.secondaryText}>Upload file</Text>
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
          ) : sampleKey ? (
            <Text style={styles.uploaded}>Uploaded</Text>
          ) : null}
        </View>
      ) : null}

      <View style={styles.consentRow}>
        <Switch
          value={consent}
          onValueChange={setConsent}
          disabled={busy}
          trackColor={{ false: colors.border, true: colors.primary }}
          thumbColor={colors.textPrimary}
        />
        <Text style={styles.consentText}>
          I confirm I own this voice or am authorized to clone and use it.
        </Text>
      </View>

      {combinedError ? <Text style={styles.error}>{combinedError}</Text> : null}

      <Pressable
        style={[styles.button, !canSubmit && styles.buttonDisabled]}
        onPress={onSubmit}
        disabled={!canSubmit}
      >
        {phase === "submitting" ? (
          <ActivityIndicator color={colors.textPrimary} />
        ) : (
          <Text style={styles.buttonText}>Create brand voice</Text>
        )}
      </Pressable>
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
  label: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  input: {
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 12,
    paddingVertical: 10,
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
  consentRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  consentText: { flex: 1, color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  error: { color: colors.error, fontSize: 13 },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: "center",
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
});
