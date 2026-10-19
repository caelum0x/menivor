/**
 * Normalizes a screen recording picked from either expo-document-picker or
 * expo-image-picker into the `LocalFile` shape the upload flow expects. Fills
 * in a missing byte size from expo-file-system and guesses a content type from
 * the file extension when the picker doesn't supply one.
 */

import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";
import * as ImagePicker from "expo-image-picker";

import type { LocalFile } from "@/lib/api";

function guessMime(name: string, fallback = "video/mp4"): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    mp4: "video/mp4",
    mov: "video/quicktime",
    m4v: "video/x-m4v",
    webm: "video/webm",
    avi: "video/x-msvideo",
    mkv: "video/x-matroska",
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

/** Opens the system document browser filtered to video files. */
export async function pickRecordingFromFiles(): Promise<LocalFile | null> {
  const result = await DocumentPicker.getDocumentAsync({
    type: "video/*",
    copyToCacheDirectory: true,
    multiple: false,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  const name = asset.name || "recording.mp4";
  return {
    uri: asset.uri,
    name,
    mimeType: asset.mimeType || guessMime(name),
    size: await ensureSize(asset.uri, asset.size),
  };
}

/** Opens the media library filtered to videos. */
export async function pickRecordingFromLibrary(): Promise<LocalFile | null> {
  const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!permission.granted) {
    throw new Error("Photo library permission is required to pick a video.");
  }

  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ImagePicker.MediaTypeOptions.Videos,
    allowsMultipleSelection: false,
    quality: 1,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  const name = asset.fileName || `recording-${Date.now()}.mp4`;
  return {
    uri: asset.uri,
    name,
    mimeType: asset.mimeType || guessMime(name),
    size: await ensureSize(asset.uri, asset.fileSize),
  };
}
