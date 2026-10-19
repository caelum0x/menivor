/**
 * Picks a brand watermark logo — a transparent PNG — from the media library
 * (expo-image-picker) or the system document browser (expo-document-picker) and
 * normalizes it into the `LocalFile` shape the shared presign/upload flow
 * expects. Mirrors lib/pick-recording.ts, but for a still PNG logo.
 *
 * The backend brand endpoint expects an image/png upload, so a non-PNG pick is
 * rejected here with a clear error rather than uploading an unsupported logo
 * (which would silently break the compose-stage overlay).
 */

import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";
import * as ImagePicker from "expo-image-picker";

import type { LocalFile } from "@/lib/api";

/** MIME type every uploaded brand logo is stored as. */
export const LOGO_CONTENT_TYPE = "image/png";

/** Thrown when the picked file is not a PNG (the only supported logo format). */
export class NotPngError extends Error {
  constructor(message = "Please choose a transparent PNG logo.") {
    super(message);
    this.name = "NotPngError";
  }
}

function isPng(name: string, mimeType?: string | null): boolean {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const mime = (mimeType ?? "").toLowerCase();
  return ext === "png" || mime === "image/png";
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

/**
 * Opens the media library filtered to images and returns the picked PNG as a
 * `LocalFile`. Returns null when the user cancels. Throws
 * {@link NotPngError} for a non-PNG selection and a permission Error when photo
 * access is denied.
 */
export async function pickLogoFromLibrary(): Promise<LocalFile | null> {
  const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!permission.granted) {
    throw new Error("Photo library permission is required to pick a logo.");
  }

  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ImagePicker.MediaTypeOptions.Images,
    allowsMultipleSelection: false,
    quality: 1,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  const name = asset.fileName || `logo-${Date.now()}.png`;
  if (!isPng(name, asset.mimeType)) {
    throw new NotPngError();
  }
  return {
    uri: asset.uri,
    name: name.toLowerCase().endsWith(".png") ? name : `${name}.png`,
    mimeType: LOGO_CONTENT_TYPE,
    size: await ensureSize(asset.uri, asset.fileSize),
  };
}

/**
 * Opens the system document browser filtered to PNG files and returns the
 * picked logo as a `LocalFile`. Returns null when the user cancels. Throws
 * {@link NotPngError} for a non-PNG selection.
 */
export async function pickLogoFromFiles(): Promise<LocalFile | null> {
  const result = await DocumentPicker.getDocumentAsync({
    type: "image/png",
    copyToCacheDirectory: true,
    multiple: false,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  const name = asset.name || "logo.png";
  if (!isPng(name, asset.mimeType)) {
    throw new NotPngError();
  }
  return {
    uri: asset.uri,
    name,
    mimeType: LOGO_CONTENT_TYPE,
    size: await ensureSize(asset.uri, asset.size),
  };
}
