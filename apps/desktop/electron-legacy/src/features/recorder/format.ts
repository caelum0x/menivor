/**
 * Small, pure formatting helpers for the recorder UI. Kept dependency-free so the
 * engine, the hook, and the panel can all share them without pulling in React.
 */

function pad2(value: number): string {
  return value.toString().padStart(2, "0");
}

/**
 * Render a millisecond duration as `mm:ss` (or `h:mm:ss` past an hour). Used for
 * the live recording clock and the review readout.
 */
export function formatDuration(totalMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(totalMs / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}:${pad2(minutes)}:${pad2(seconds)}`;
  return `${pad2(minutes)}:${pad2(seconds)}`;
}

/** Render a byte count as a compact, human-friendly size (KB / MB / GB). */
export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 KB";

  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)} KB`;

  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;

  return `${(mb / 1024).toFixed(2)} GB`;
}
