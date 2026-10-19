/**
 * Resume across devices (MV6): read where the viewer stopped, then save the
 * position every 10 s while playing and on pause. Saving never interrupts
 * playback; a failed save is retried at the next tick.
 */

import { getProgress, putProgress } from "./api";

export const SAVE_EVERY_MS = 10_000;

export async function resumePosition(handle: string, session: string, titleId: string): Promise<number> {
  try {
    const view = await getProgress(handle, session, titleId);
    return view.finished ? 0 : view.position_s;
  } catch {
    return 0;
  }
}

export function trackProgress(
  video: HTMLVideoElement,
  handle: string,
  session: string,
  titleId: string,
  save: typeof putProgress = putProgress,
): () => void {
  let last = -1;
  const flush = () => {
    const at = Math.floor(video.currentTime);
    if (at <= 0 || at === last) return;
    last = at;
    save(handle, session, titleId, at, Number.isFinite(video.duration) ? video.duration : 0).catch(() => {
      last = -1;
    });
  };
  const timer = setInterval(() => {
    if (!video.paused) flush();
  }, SAVE_EVERY_MS);
  video.addEventListener("pause", flush);
  video.addEventListener("ended", flush);
  return () => {
    clearInterval(timer);
    video.removeEventListener("pause", flush);
    video.removeEventListener("ended", flush);
    flush();
  };
}
