/**
 * Menivor OTT web player core (Wave P PM2.5, MV4). Framework-free so the web
 * app, the embed page and later clients share one playback path.
 *
 * - `attach(video, url, loadHls)`: Safari (and any browser that plays HLS
 *   natively) gets the URL directly; everyone else gets hls.js (Apache-2.0),
 *   loaded only when needed. AES-128 tier-1 streams play in both without EME.
 * - `SoundFocus`: only one player makes sound at a time.
 * - `RefreshingSource`: asks for a fresh playback token before the current one
 *   expires (tokens live 10 minutes or less) and resumes at the same position.
 */

export const HLS_MIME = "application/vnd.apple.mpegurl";

export interface HlsLike {
  loadSource(url: string): void;
  attachMedia(media: HTMLMediaElement): void;
  destroy(): void;
  on?(event: string, handler: (...args: unknown[]) => void): void;
}

export interface HlsConstructor {
  new (config?: Record<string, unknown>): HlsLike;
  isSupported(): boolean;
  Events?: { ERROR?: string };
}

export type LoadHls = () => Promise<HlsConstructor>;

export interface Attached {
  readonly engine: "native" | "hls.js";
  destroy(): void;
}

export function playsHlsNatively(video: Pick<HTMLVideoElement, "canPlayType">): boolean {
  return video.canPlayType(HLS_MIME) !== "";
}

export async function attach(
  video: HTMLVideoElement,
  url: string,
  loadHls: LoadHls,
  onFatal?: (reason: string) => void,
): Promise<Attached> {
  if (playsHlsNatively(video)) {
    video.src = url;
    return { engine: "native", destroy: () => video.removeAttribute("src") };
  }
  const Hls = await loadHls();
  if (!Hls.isSupported()) throw new Error("This browser cannot play this video.");
  const hls = new Hls({ maxBufferLength: 30, enableWorker: true });
  if (onFatal && hls.on && Hls.Events?.ERROR) {
    hls.on(Hls.Events.ERROR, (...args: unknown[]) => {
      const data = args[1] as { fatal?: boolean; details?: string } | undefined;
      if (data?.fatal) onFatal(data.details ?? "playback error");
    });
  }
  hls.loadSource(url);
  hls.attachMedia(video);
  return { engine: "hls.js", destroy: () => hls.destroy() };
}

/** Only one registered player plays with sound; unmuting one mutes the rest. */
export class SoundFocus {
  private readonly players = new Set<HTMLMediaElement>();

  register(media: HTMLMediaElement): () => void {
    this.players.add(media);
    const onVolume = () => {
      if (!media.muted) this.focus(media);
    };
    media.addEventListener("volumechange", onVolume);
    media.addEventListener("play", onVolume);
    return () => {
      media.removeEventListener("volumechange", onVolume);
      media.removeEventListener("play", onVolume);
      this.players.delete(media);
    };
  }

  focus(active: HTMLMediaElement): void {
    for (const media of this.players) {
      if (media !== active && !media.muted) media.muted = true;
    }
  }
}

export const soundFocus = new SoundFocus();

export interface PlaybackGrant {
  readonly manifest_url: string;
  readonly expires_at: number;
  readonly session_id: string;
  readonly protected: boolean;
  /** Paid titles only (Wave Q QM1.5): the short code the player shows over the picture. */
  readonly viewer_mark?: string;
}

/** Re-asks for a grant `leadSeconds` before expiry; returns a stop function. */
export function refreshBeforeExpiry(
  grant: PlaybackGrant,
  renew: () => Promise<PlaybackGrant>,
  apply: (next: PlaybackGrant) => void,
  options: { leadSeconds?: number; now?: () => number; schedule?: (fn: () => void, ms: number) => unknown; cancel?: (handle: unknown) => void } = {},
): () => void {
  const lead = options.leadSeconds ?? 60;
  const now = options.now ?? (() => Date.now() / 1000);
  const schedule = options.schedule ?? ((fn, ms) => setTimeout(fn, ms));
  const cancel = options.cancel ?? ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>));
  let handle: unknown;
  let stopped = false;
  const arm = (current: PlaybackGrant) => {
    const wait = Math.max(5, current.expires_at - now() - lead) * 1000;
    handle = schedule(async () => {
      if (stopped) return;
      const next = await renew();
      apply(next);
      arm(next);
    }, wait);
  };
  arm(grant);
  return () => {
    stopped = true;
    cancel(handle);
  };
}

/** Copy for protection: only "protected streaming", and only where tier 1 is live. Never "DRM". */
export function protectionLabel(isProtected: boolean, tierOneLive: boolean): string {
  return isProtected && tierOneLive ? "Protected streaming" : "";
}
