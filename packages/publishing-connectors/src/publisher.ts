/**
 * The `Publisher` contract every platform client implements. Tokens are passed
 * **in** per call (never read from env/store) — the API decrypts Fernet tokens
 * and injects them; connectors are stateless (security seam).
 */

import type { Platform, PlatformCaps } from "./caps.js";

export interface PublishRequest {
  videoUrl: string;
  caption: string;
  aspect: string;
  durationS: number;
  /** Platform where the source was watermarked, if any (cross-post guard). */
  watermarkSource?: string;
}

export interface PublishResult {
  platform: Platform;
  postId: string;
  url: string;
}

export interface ConnectorError {
  kind: "auth" | "cap" | "watermark" | "rate" | "platform";
  message: string;
  platform: Platform;
  retryable: boolean;
}

/** Read-only analytics snapshot normalized to the shared shape. */
export interface AnalyticsSnapshot {
  platform: Platform;
  views: number;
  watch_time_s: number;
  retention_pct: number;
}

export interface Publisher {
  readonly platform: Platform;
  caps(): PlatformCaps;
  scheduleSupported(): boolean;
  /** @param token per-call Fernet-decrypted access token, injected by the API. */
  publish(req: PublishRequest, token: string): Promise<PublishResult>;
  refresh(refreshToken: string): Promise<{ accessToken: string; expiresIn: number }>;
  fetchAnalytics(postId: string, token: string): Promise<AnalyticsSnapshot>;
}
