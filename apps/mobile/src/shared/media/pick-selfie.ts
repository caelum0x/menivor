/**
 * Picks a creator selfie (a still image) from the media library
 * (expo-image-picker) or the system document browser (expo-document-picker) and
 * normalizes it into the `LocalFile` shape the shared presign/upload flow
 * expects. Mirrors lib/pick-logo.ts, but accepts any common photo format (the
 * photo→avatar endpoint turns it into a HeyGen talking-photo).
 *
 * A non-image pick is rejected here with a clear error rather than uploading an
 * unsupported file that HeyGen would reject downstream.
 */

import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";
import * as ImagePicker from "expo-image-picker";

import type { LocalFile } from "@/lib/api";

/** Supported selfie image extensions → MIME type. */
const IMAGE_MIME_BY_EXT: Readonly<Record<string, string>> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  heic: "image/heic",
  heif: "image/heif",
};

/** Fallback MIME when the picker supplies neither type nor a known extension. */
const DEFAULT_IMAGE_MIME = "image/jpeg";

/** Thrown when the picked file is not a supported image format. */
export class NotAnImageError extends Error {
  constructor(message = "Please choose a photo (JPEG, PNG, WebP or HEIC).") {
    super(message);
    this.name = "NotAnImageError";
  }
}

function extOf(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

function isImage(name: string, mimeType?: string | null): boolean {
  const mime = (mimeType ?? "").toLowerCase();
  if (mime.startsWith("image/")) return true;
  return extOf(name) in IMAGE_MIME_BY_EXT;
}

/** Resolves the MIME type from the picker's value or the filename extension. */
function resolveMime(name: string, mimeType?: string | null): string {
  const mime = (mimeType ?? "").toLowerCase();
  if (mime.startsWith("image/")) return mime;
  return IMAGE_MIME_BY_EXT[extOf(name)] ?? DEFAULT_IMAGE_MIME;
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
 * Opens the media library filtered to images and returns the picked photo as a
 * `LocalFile`. Returns null when the user cancels. Throws {@link NotAnImageError}
 * for a non-image selection and a permission Error when photo access is denied.
 */
export async function pickSelfieFromLibrary(): Promise<LocalFile | null> {
  const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!permission.granted) {
    throw new Error("Photo library permission is required to pick a selfie.");
  }

  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ImagePicker.MediaTypeOptions.Images,
    allowsMultipleSelection: false,
    quality: 1,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  const name = asset.fileName || `selfie-${Date.now()}.jpg`;
  if (!isImage(name, asset.mimeType)) {
    throw new NotAnImageError();
  }
  return {
    uri: asset.uri,
    name,
    mimeType: resolveMime(name, asset.mimeType),
    size: await ensureSize(asset.uri, asset.fileSize),
  };
}

/**
 * Opens the device camera to capture a selfie and returns it as a `LocalFile`.
 * Returns null when the user cancels. Throws a permission Error when camera
 * access is denied.
 */
export async function captureSelfie(): Promise<LocalFile | null> {
  const permission = await ImagePicker.requestCameraPermissionsAsync();
  if (!permission.granted) {
    throw new Error("Camera permission is required to take a selfie.");
  }

  const result = await ImagePicker.launchCameraAsync({
    cameraType: ImagePicker.CameraType.front,
    allowsMultipleSelection: false,
    quality: 1,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  const name = asset.fileName || `selfie-${Date.now()}.jpg`;
  return {
    uri: asset.uri,
    name,
    mimeType: resolveMime(name, asset.mimeType),
    size: await ensureSize(asset.uri, asset.fileSize),
  };
}

/**
 * Opens the system document browser filtered to images and returns the picked
 * photo as a `LocalFile`. Returns null when the user cancels. Throws
 * {@link NotAnImageError} for a non-image selection.
 */
export async function pickSelfieFromFiles(): Promise<LocalFile | null> {
  const result = await DocumentPicker.getDocumentAsync({
    type: "image/*",
    copyToCacheDirectory: true,
    multiple: false,
  });
  if (result.canceled || result.assets.length === 0) return null;

  const asset = result.assets[0];
  const name = asset.name || "selfie.jpg";
  if (!isImage(name, asset.mimeType)) {
    throw new NotAnImageError();
  }
  return {
    uri: asset.uri,
    name,
    mimeType: resolveMime(name, asset.mimeType),
    size: await ensureSize(asset.uri, asset.size),
  };
}
