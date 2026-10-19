/**
 * File pickers for the legacy MoneyPrinterTurbo standalone stock libraries —
 * the background-music library (`POST /musics`) and the local video-materials
 * library (`POST /video_materials`). Each opens the system document browser and
 * normalizes the pick into the shared `LocalFile` shape the upload flow expects
 * (mirrors `pick-voice-sample.ts` / `pick-video.ts`), filling a missing byte
 * size from expo-file-system and guessing a content type from the extension.
 */

import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";

import type { LocalFile } from "@/lib/api";

/** Extensions the BGM library accepts (matches the backend allow-list). */
export const BGM_EXTENSIONS: readonly string[] = [
  "mp3",
  "m4a",
  "aac",
  "wav",
  "flac",
  "ogg",
  "opus",
  "wma",
];

/** Extensions the video-materials library accepts (matches the backend). */
export const VIDEO_MATERIAL_EXTENSIONS: readonly string[] = [
  "mp4",
  "mov",
  "avi",
  "flv",
  "mkv",
  "jpg",
  "jpeg",
  "png",
];

const BGM_MIME_BY_EXT: Readonly<Record<string, string>> = {
  mp3: "audio/mpeg",
  m4a: "audio/mp4",
  aac: "audio/aac",
  wav: "audio/wav",
  flac: "audio/flac",
  ogg: "audio/ogg",
  opus: "audio/opus",
  wma: "audio/x-ms-wma",
};

const VIDEO_MATERIAL_MIME_BY_EXT: Readonly<Record<string, string>> = {
  mp4: "video/mp4",
  mov: "video/quicktime",
  avi: "video/x-msvideo",
  flv: "video/x-flv",
  mkv: "video/x-matroska",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
};

/** The extension of a filename, lower-cased and without the dot. */
export function extensionOf(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

function mimeFor(
  name: string,
  supplied: string | null | undefined,
  table: Readonly<Record<string, string>>,
  fallback: string,
): string {
  if (supplied && supplied.length > 0) return supplied;
  return table[extensionOf(name)] ?? fallback;
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

/** Opens the document browser filtered to audio for a BGM upload. */
export async function pickBgmFileFromFiles(): Promise<LocalFile | null> {
  const result = await DocumentPicker.getDocumentAsync({
    type: "audio/*",
    copyToCacheDirectory: true,
    multiple: false,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  const name = asset.name || "track.mp3";
  return {
    uri: asset.uri,
    name,
    mimeType: mimeFor(name, asset.mimeType, BGM_MIME_BY_EXT, "audio/mpeg"),
    size: await ensureSize(asset.uri, asset.size),
  };
}

/** Opens the document browser filtered to video/image for a material upload. */
export async function pickVideoMaterialFromFiles(): Promise<LocalFile | null> {
  const result = await DocumentPicker.getDocumentAsync({
    type: ["video/*", "image/*"],
    copyToCacheDirectory: true,
    multiple: false,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  const name = asset.name || "material.mp4";
  return {
    uri: asset.uri,
    name,
    mimeType: mimeFor(name, asset.mimeType, VIDEO_MATERIAL_MIME_BY_EXT, "video/mp4"),
    size: await ensureSize(asset.uri, asset.size),
  };
}
