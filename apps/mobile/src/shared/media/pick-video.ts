/**
 * Picks a screen recording / video clip from the media library
 * (expo-image-picker) or the system document browser (expo-document-picker) and
 * normalizes it into the `LocalFile` shape the shared presign/upload flow
 * expects. Mirrors `pick-selfie.ts`, but for the video the compose stage layers
 * under (`screen_recording_key` / a template's `gameplay_clip`).
 */

import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";
import * as ImagePicker from "expo-image-picker";

import type { LocalFile } from "@/lib/api";

/** Supported video extensions → MIME type. */
const VIDEO_MIME_BY_EXT: Readonly<Record<string, string>> = {
  mp4: "video/mp4",
  mov: "video/quicktime",
  m4v: "video/x-m4v",
  webm: "video/webm",
};

const DEFAULT_VIDEO_MIME = "video/mp4";

/** Thrown when the picked file is not a supported video format. */
export class NotAVideoError extends Error {
  constructor(message = "Please choose a video (MP4, MOV, M4V or WebM).") {
    super(message);
    this.name = "NotAVideoError";
  }
}

function extOf(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

function mimeFor(name: string, supplied?: string | null): string {
  if (supplied && supplied.startsWith("video/")) return supplied;
  return VIDEO_MIME_BY_EXT[extOf(name)] ?? DEFAULT_VIDEO_MIME;
}

async function sizeOf(uri: string, supplied?: number): Promise<number> {
  if (typeof supplied === "number" && supplied > 0) return supplied;
  try {
    const info = await FileSystem.getInfoAsync(uri);
    return info.exists && "size" in info ? (info.size as number) : 0;
  } catch {
    return 0;
  }
}

/** Pick a video and normalize it; returns null if the user cancels. */
export async function pickVideo(): Promise<LocalFile | null> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (perm.granted) {
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Videos,
      allowsMultipleSelection: false,
      quality: 1,
    });
    if (res.canceled) return null;
    const a = res.assets[0];
    const name = a.fileName ?? `recording.${extOf(a.uri) || "mp4"}`;
    if (!name.match(/\.(mp4|mov|m4v|webm)$/i) && !(a.mimeType ?? "").startsWith("video/")) {
      throw new NotAVideoError();
    }
    return { uri: a.uri, name, mimeType: mimeFor(name, a.mimeType), size: await sizeOf(a.uri, a.fileSize) };
  }

  // Fall back to the document browser when library permission is denied.
  const doc = await DocumentPicker.getDocumentAsync({ type: "video/*", copyToCacheDirectory: true });
  if (doc.canceled) return null;
  const f = doc.assets[0];
  if (!(f.mimeType ?? "").startsWith("video/") && !f.name.match(/\.(mp4|mov|m4v|webm)$/i)) {
    throw new NotAVideoError();
  }
  return { uri: f.uri, name: f.name, mimeType: mimeFor(f.name, f.mimeType), size: await sizeOf(f.uri, f.size ?? 0) };
}
