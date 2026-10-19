/**
 * Thin hook around expo-av's `Audio.Recording` for capturing a 30–60s brand
 * voice sample. Owns the recorder lifecycle (permission -> record -> stop) and
 * exposes a live duration, so the UI can guide the creator toward a usable
 * sample length. `stop()` resolves with a `LocalFile` ready for the shared
 * upload flow (lib/api.ts::presignAndUpload).
 *
 * A single recorder may exist at a time (an expo-av constraint), so the hook
 * keeps the active instance in a ref and always unloads it on stop / unmount.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Audio } from "expo-av";
import * as FileSystem from "expo-file-system/legacy";

import type { LocalFile } from "@/lib/api";
import { describeError } from "@/components/me/errors";

export type RecorderStatus = "idle" | "recording" | "stopping";

export interface VoiceRecorder {
  status: RecorderStatus;
  /** Elapsed recording time in milliseconds (0 while idle). */
  durationMs: number;
  error: string | null;
  /** Requests mic permission and begins recording. */
  start: () => Promise<void>;
  /** Stops + unloads, returning the captured file (or null if nothing ran). */
  stop: () => Promise<LocalFile | null>;
}

/** Derives a `LocalFile` from a finished recording's URI. */
async function toLocalFile(uri: string): Promise<LocalFile> {
  // expo-av writes an .m4a container on both platforms by default.
  const name = `voice-sample-${Date.now()}.m4a`;
  let size = 0;
  try {
    const info = await FileSystem.getInfoAsync(uri);
    if (info.exists && typeof info.size === "number") size = info.size;
  } catch {
    size = 0;
  }
  return { uri, name, mimeType: "audio/mp4", size };
}

export function useVoiceRecorder(): VoiceRecorder {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [durationMs, setDurationMs] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const recordingRef = useRef<Audio.Recording | null>(null);

  // Best-effort unload if the component unmounts mid-recording.
  useEffect(() => {
    return () => {
      const active = recordingRef.current;
      recordingRef.current = null;
      if (active) {
        active.stopAndUnloadAsync().catch(() => {
          /* best-effort cleanup */
        });
      }
    };
  }, []);

  const start = useCallback(async () => {
    if (recordingRef.current) return;
    setError(null);
    setDurationMs(0);
    try {
      const permission = await Audio.requestPermissionsAsync();
      if (!permission.granted) {
        throw new Error("Microphone permission is required to record a voice sample.");
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
        (recordingStatus) => {
          if (recordingStatus.isRecording) {
            setDurationMs(recordingStatus.durationMillis ?? 0);
          }
        },
        250,
      );
      recordingRef.current = recording;
      setStatus("recording");
    } catch (err) {
      recordingRef.current = null;
      setStatus("idle");
      setError(describeError(err, "Could not start recording."));
    }
  }, []);

  const stop = useCallback(async (): Promise<LocalFile | null> => {
    const active = recordingRef.current;
    if (!active) return null;
    setStatus("stopping");
    try {
      await active.stopAndUnloadAsync();
      // Reset iOS audio session so subsequent playback isn't stuck in record mode.
      await Audio.setAudioModeAsync({ allowsRecordingIOS: false }).catch(() => {
        /* non-fatal */
      });
      const uri = active.getURI();
      recordingRef.current = null;
      setStatus("idle");
      if (!uri) {
        setError("Recording produced no audio file.");
        return null;
      }
      return await toLocalFile(uri);
    } catch (err) {
      recordingRef.current = null;
      setStatus("idle");
      setError(describeError(err, "Could not stop recording."));
      return null;
    }
  }, []);

  return { status, durationMs, error, start, stop };
}
