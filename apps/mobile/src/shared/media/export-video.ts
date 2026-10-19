import * as FileSystem from "expo-file-system/legacy";
import { Platform, Share } from "react-native";

import {
  currentLocalUri,
  ensureLocalFolderMigrated,
  localFolderUri,
  resolveLocalRead,
} from "./local-folder";

export interface ExportVideoArgs {
  url: string;
  jobId: string;
  durationSeconds?: number | null;
  onProgress?: (progress: number | null) => void;
}

export type ExportReceiptStatus =
  | "downloading"
  | "ready"
  | "shared"
  | "failed";

export type ExportFailureStep = "download" | "share";

/**
 * Durable, device-local record of an export attempt. The receipt is keyed by
 * job id so closing the screen (or the app) never turns export into an
 * untraceable one-off action.
 */
export interface ExportReceipt {
  jobId: string;
  fileName: string;
  localUri: string;
  sizeBytes: number | null;
  durationSeconds: number | null;
  attemptCount: number;
  status: ExportReceiptStatus;
  shareStatus: "not_opened" | "dismissed" | "shared";
  retryAvailable: boolean;
  failedStep: ExportFailureStep | null;
  errorMessage: string | null;
  lastAttemptAt: string;
  downloadedAt: string | null;
}

export class ExportVideoError extends Error {
  readonly receipt: ExportReceipt;

  constructor(message: string, receipt: ExportReceipt) {
    super(message);
    this.name = "ExportVideoError";
    this.receipt = receipt;
  }
}

function safeJobId(jobId: string): string {
  return jobId.replace(/[^A-Za-z0-9_-]/g, "_");
}

function exportDirectory(): string {
  const base = localFolderUri();
  if (!base) {
    throw new Error("Device storage is unavailable for video export.");
  }
  return `${base}exports/`;
}

function localVideoPath(jobId: string): string {
  return `${exportDirectory()}menivor-${safeJobId(jobId)}.mp4`;
}

function receiptFile(jobId: string): string {
  return `menivor-${safeJobId(jobId)}.receipt.json`;
}

/** Receipt name used before the Menivor rename (still read as a fallback). */
function legacyReceiptFile(jobId: string): string {
  return `reelforge-${safeJobId(jobId)}.receipt.json`;
}

function receiptPath(jobId: string): string {
  return `${exportDirectory()}${receiptFile(jobId)}`;
}

async function ensureExportDirectory(): Promise<void> {
  await ensureLocalFolderMigrated();
  const directory = exportDirectory();
  const info = await FileSystem.getInfoAsync(directory);
  if (!info.exists) {
    await FileSystem.makeDirectoryAsync(directory, { intermediates: true });
  }
}

async function saveExportReceipt(receipt: ExportReceipt): Promise<void> {
  await ensureExportDirectory();
  await FileSystem.writeAsStringAsync(
    receiptPath(receipt.jobId),
    JSON.stringify(receipt),
  );
}

function isReceipt(value: unknown, jobId: string): value is ExportReceipt {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ExportReceipt>;
  return (
    candidate.jobId === jobId &&
    typeof candidate.fileName === "string" &&
    typeof candidate.localUri === "string" &&
    typeof candidate.attemptCount === "number" &&
    typeof candidate.status === "string"
  );
}

/** Load the last export outcome for one job from app-owned device storage. */
export async function loadExportReceipt(
  jobId: string,
): Promise<ExportReceipt | null> {
  try {
    const path =
      (await resolveLocalRead(`exports/${receiptFile(jobId)}`)) ??
      (await resolveLocalRead(`exports/${legacyReceiptFile(jobId)}`));
    if (!path) return null;
    const value: unknown = JSON.parse(await FileSystem.readAsStringAsync(path));
    if (!isReceipt(value, jobId)) return null;
    // Receipts written before the folder move point into reelforge/; follow the
    // file to menivor/ when it was moved, else keep the original location.
    const moved = currentLocalUri(value.localUri);
    if (moved !== value.localUri) {
      const info = await FileSystem.getInfoAsync(moved);
      if (info.exists) return { ...value, localUri: moved };
    }
    return value;
  } catch {
    // A missing/corrupt local receipt must not prevent a fresh export.
    return null;
  }
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

async function reusableLocalFile(
  receipt: ExportReceipt | null,
): Promise<{ uri: string; size: number } | null> {
  const downloadFinished =
    receipt?.status === "ready" ||
    receipt?.status === "shared" ||
    (receipt?.status === "failed" && receipt.failedStep === "share");
  if (!receipt || !downloadFinished) return null;

  try {
    const info = await FileSystem.getInfoAsync(receipt.localUri);
    if (!info.exists || typeof info.size !== "number" || info.size <= 0) {
      return null;
    }
    return { uri: receipt.localUri, size: info.size };
  } catch {
    return null;
  }
}

/**
 * Download the final render to durable app-owned storage, persist an output
 * receipt, then hand the local MP4 to the iOS share sheet. A share-only failure
 * reuses the completed download on retry; a download failure retries against
 * the same job id and file location.
 */
export async function exportVideoToDevice({
  url,
  jobId,
  durationSeconds,
  onProgress,
}: Readonly<ExportVideoArgs>): Promise<ExportReceipt> {
  if (Platform.OS !== "ios") {
    throw new Error(
      "Direct file export is currently available in the iPhone build.",
    );
  }
  if (!/^https?:\/\//i.test(url)) {
    throw new Error("The finished video URL is invalid. Refresh the render.");
  }

  await ensureExportDirectory();
  const previous = await loadExportReceipt(jobId);
  const target = localVideoPath(jobId);
  const now = new Date().toISOString();
  const attemptCount = (previous?.attemptCount ?? 0) + 1;
  const baseReceipt: ExportReceipt = {
    jobId,
    fileName: `menivor-${safeJobId(jobId)}.mp4`,
    localUri: target,
    sizeBytes: null,
    durationSeconds:
      typeof durationSeconds === "number" && durationSeconds > 0
        ? durationSeconds
        : (previous?.durationSeconds ?? null),
    attemptCount,
    status: "downloading",
    shareStatus: "not_opened",
    retryAvailable: true,
    failedStep: null,
    errorMessage: null,
    lastAttemptAt: now,
    downloadedAt: previous?.downloadedAt ?? null,
  };
  await saveExportReceipt(baseReceipt);

  let localFile = await reusableLocalFile(previous);
  let downloadedNow = false;
  if (!localFile) {
    try {
      // A partial file from a failed attempt cannot be presented as a complete
      // export. Replace it while keeping the stable per-job destination.
      await FileSystem.deleteAsync(target, { idempotent: true });
      onProgress?.(0);

      const download = FileSystem.createDownloadResumable(
        url,
        target,
        {
          sessionType: FileSystem.FileSystemSessionType.BACKGROUND,
        },
        ({ totalBytesWritten, totalBytesExpectedToWrite }) => {
          onProgress?.(
            totalBytesExpectedToWrite > 0
              ? Math.min(1, totalBytesWritten / totalBytesExpectedToWrite)
              : null,
          );
        },
      );

      const result = await download.downloadAsync();
      if (!result?.uri || result.status < 200 || result.status >= 300) {
        throw new Error("The finished video could not be downloaded.");
      }
      const info = await FileSystem.getInfoAsync(result.uri);
      if (!info.exists || typeof info.size !== "number" || info.size <= 0) {
        throw new Error("The downloaded video file is empty.");
      }
      localFile = { uri: result.uri, size: info.size };
      downloadedNow = true;
      onProgress?.(1);
    } catch (error) {
      const message = errorMessage(error, "Video download failed.");
      const failedReceipt: ExportReceipt = {
        ...baseReceipt,
        status: "failed",
        failedStep: "download",
        errorMessage: message,
      };
      await saveExportReceipt(failedReceipt);
      throw new ExportVideoError(message, failedReceipt);
    }
  } else {
    onProgress?.(1);
  }

  const readyReceipt: ExportReceipt = {
    ...baseReceipt,
    localUri: localFile.uri,
    sizeBytes: localFile.size,
    status: "ready",
    retryAvailable: false,
    downloadedAt:
      downloadedNow || !previous?.downloadedAt
        ? new Date().toISOString()
        : previous.downloadedAt,
  };
  await saveExportReceipt(readyReceipt);

  try {
    const shareResult = await Share.share(
      { title: "Menivor video", url: localFile.uri },
      { subject: "Menivor video export" },
    );
    const shared = shareResult.action === Share.sharedAction;
    const completedReceipt: ExportReceipt = {
      ...readyReceipt,
      status: shared ? "shared" : "ready",
      shareStatus: shared ? "shared" : "dismissed",
    };
    await saveExportReceipt(completedReceipt);
    return completedReceipt;
  } catch (error) {
    const message = errorMessage(error, "The share sheet could not be opened.");
    const failedReceipt: ExportReceipt = {
      ...readyReceipt,
      status: "failed",
      failedStep: "share",
      errorMessage: message,
      retryAvailable: true,
    };
    await saveExportReceipt(failedReceipt);
    throw new ExportVideoError(message, failedReceipt);
  }
}
