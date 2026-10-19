/**
 * Durable storage for draft clips.
 *
 * Picker results point into the OS picker/cache directories, which iOS and
 * Android may purge at any time. A saved draft must still have its clip when
 * the creator comes back to it, so the clip is copied into the app's document
 * directory (never purged) before the draft is persisted, and removed again
 * when the draft is deleted or turned into a job.
 */

import * as FileSystem from "expo-file-system/legacy";

import { deleteDraft, getDraft, type ReelDraft } from "./drafts";

type DraftMedia = NonNullable<ReelDraft["media"]>;

function draftMediaDirectory(): string {
  if (!FileSystem.documentDirectory) {
    throw new Error("Device storage is unavailable for saving drafts.");
  }
  return `${FileSystem.documentDirectory}menivor/drafts/`;
}

function safeFileName(name: string): string {
  const cleaned = name.replace(/[^A-Za-z0-9._-]/g, "_").slice(-80);
  return cleaned || "clip.mp4";
}

/** True when `uri` already lives in the durable drafts directory. */
function isDurable(uri: string): boolean {
  return (
    !!FileSystem.documentDirectory &&
    uri.startsWith(`${FileSystem.documentDirectory}menivor/drafts/`)
  );
}

/**
 * Copy a picked clip into app storage and return the media record pointing at
 * the durable copy. Throws when the copy fails so the caller can tell the user
 * the draft was not saved with its clip.
 */
export async function persistDraftMedia(media: DraftMedia): Promise<DraftMedia> {
  if (isDurable(media.uri)) return media;
  const directory = draftMediaDirectory();
  await FileSystem.makeDirectoryAsync(directory, { intermediates: true });
  const target = `${directory}${Date.now()}-${safeFileName(media.name)}`;
  await FileSystem.copyAsync({ from: media.uri, to: target });
  return { ...media, uri: target };
}

/** Best-effort removal of a draft's durable clip copy. Never throws. */
export async function removeDraftMedia(media: ReelDraft["media"]): Promise<void> {
  if (!media || !isDurable(media.uri)) return;
  await FileSystem.deleteAsync(media.uri, { idempotent: true }).catch(
    () => undefined,
  );
}

/** Whether the draft's clip file is still on the device. */
export async function draftMediaAvailable(
  media: ReelDraft["media"],
): Promise<boolean> {
  if (!media) return false;
  try {
    const info = await FileSystem.getInfoAsync(media.uri);
    return info.exists;
  } catch {
    return false;
  }
}

/**
 * Delete a draft and its durable clip copy. Returns the remaining drafts
 * (newest first), exactly like {@link deleteDraft}.
 */
export async function discardDraft(id: string): Promise<ReelDraft[]> {
  const draft = await getDraft(id);
  const remaining = await deleteDraft(id);
  await removeDraftMedia(draft?.media);
  return remaining;
}
