import * as FileSystem from "expo-file-system/legacy";
import { Platform, Share } from "react-native";

/**
 * Save/share the generated cover image. There is no expo-sharing or
 * media-library dependency in this app, so we lean on the platform share sheet
 * (React Native's built-in `Share`), which already exposes "Save Image" /
 * "Save to Files" on iOS and the equivalent targets on Android.
 *
 * We first try to download the remote JPG into the app cache and share the
 * local `file://` URI (best experience — the OS treats it as an image and
 * offers Save to Photos). If the download fails for any reason we degrade to
 * sharing the presigned URL as a link, so the action never hard-fails.
 */

/** Derives a stable, filesystem-safe local filename for a job's cover. */
function localCoverPath(jobId: string): string {
  const safeId = jobId.replace(/[^A-Za-z0-9_-]/g, "_");
  // cacheDirectory is always present on native; guard for web/types anyway.
  const dir = FileSystem.cacheDirectory ?? FileSystem.documentDirectory ?? "";
  return `${dir}cover-${safeId}.jpg`;
}

export interface ShareCoverArgs {
  /** Absolute (presigned) URL of the rendered cover image. */
  url: string;
  /** Job id — used only to name the downloaded file. */
  jobId: string;
  /** Message/title shown in the share sheet. */
  message?: string;
}

/**
 * Downloads the cover then opens the OS share sheet on the local file. Returns
 * `true` when the user completed a share action, `false` when they dismissed it.
 * Throws only on a genuinely unrecoverable error (e.g. Share unavailable).
 */
export async function saveOrShareCover({
  url,
  jobId,
  message = "My reel cover",
}: Readonly<ShareCoverArgs>): Promise<boolean> {
  let shareUrl = url;

  try {
    const target = localCoverPath(jobId);
    const { uri } = await FileSystem.downloadAsync(url, target);
    if (uri) shareUrl = uri;
  } catch {
    // Fall back to sharing the remote URL directly.
    shareUrl = url;
  }

  // iOS uses `url` for a file/link; Android only surfaces `message`, so include
  // the link there too.
  const result = await Share.share(
    Platform.OS === "ios"
      ? { url: shareUrl, message }
      : { message: `${message}\n${shareUrl}` },
  );

  return result.action === Share.sharedAction;
}
