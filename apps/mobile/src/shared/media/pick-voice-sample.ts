/**
 * Picks a voice sample (an audio file) from the system document browser and
 * normalizes it into the `LocalFile` shape the shared upload flow expects
 * (mirrors lib/pick-recording.ts, but for audio). Fills in a missing byte size
 * from expo-file-system and guesses a content type from the file extension when
 * the picker doesn't supply one.
 */

import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";

import type { LocalFile } from "@/lib/api";

function guessAudioMime(name: string, fallback = "audio/mpeg"): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    mp3: "audio/mpeg",
    m4a: "audio/mp4",
    mp4: "audio/mp4",
    aac: "audio/aac",
    wav: "audio/wav",
    caf: "audio/x-caf",
    ogg: "audio/ogg",
    webm: "audio/webm",
    flac: "audio/flac",
  };
  return map[ext] ?? fallback;
}

async function ensureSize(uri: string, size?: number | null): Promise<number> {
  if (typeof size === "number" && size > 0) return size;
  try {
    const info = await FileSystem.getInfoAsync(uri);
    return info.exists && typeof info.size === "number" ? info.size : 0;
  } catch {
    return 0;
  }
}

/** Opens the system document browser filtered to audio files. */
export async function pickVoiceSampleFromFiles(): Promise<LocalFile | null> {
  const result = await DocumentPicker.getDocumentAsync({
    type: "audio/*",
    copyToCacheDirectory: true,
    multiple: false,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  const name = asset.name || "voice-sample.mp3";
  return {
    uri: asset.uri,
    name,
    mimeType: asset.mimeType || guessAudioMime(name),
    size: await ensureSize(asset.uri, asset.size),
  };
}
