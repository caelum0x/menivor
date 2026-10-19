/**
 * Instagram Graph API adapter — 2-step Reels publish (create container → publish).
 * Token injected per call. Mirrors `publishing/connectors/instagram.py`.
 */
import { capsFor, type PlatformCaps } from "../caps.js";
import { httpJson, type HttpOptions } from "../http.js";
import type { AnalyticsSnapshot, Publisher, PublishRequest, PublishResult } from "../publisher.js";

const GRAPH = "https://graph.facebook.com/v19.0";

/** Requires the IG business account id (passed via the token as `${igUserId}:${token}`). */
export class InstagramPublisher implements Publisher {
  readonly platform = "instagram" as const;
  constructor(private readonly http: <T>(u: string, o?: HttpOptions) => Promise<T> = httpJson) {}

  caps(): PlatformCaps { return capsFor("instagram")!; }
  scheduleSupported(): boolean { return false; }

  async publish(req: PublishRequest, token: string): Promise<PublishResult> {
    const [igUserId, accessToken] = token.split(":");
    // 1) create a REELS media container
    const container = await this.http<{ id: string }>(
      `${GRAPH}/${igUserId}/media`,
      { method: "POST", token: accessToken,
        body: { media_type: "REELS", video_url: req.videoUrl, caption: req.caption.slice(0, this.caps().caption_max) } },
    );
    // 2) publish it (production should poll container status first)
    const published = await this.http<{ id: string }>(
      `${GRAPH}/${igUserId}/media_publish`,
      { method: "POST", token: accessToken, body: { creation_id: container.id } },
    );
    return { platform: "instagram", postId: published.id, url: `https://www.instagram.com/reel/${published.id}/` };
  }

  async refresh(refreshToken: string): Promise<{ accessToken: string; expiresIn: number }> {
    // IG uses long-lived-token refresh; refreshToken IS the long-lived token.
    const res = await this.http<{ access_token: string; expires_in: number }>(
      `${GRAPH}/refresh_access_token?grant_type=ig_refresh_token&access_token=${encodeURIComponent(refreshToken)}`,
    );
    return { accessToken: res.access_token, expiresIn: res.expires_in };
  }

  async fetchAnalytics(postId: string, token: string): Promise<AnalyticsSnapshot> {
    const [, accessToken] = token.split(":");
    const res = await this.http<{ data: Array<{ name: string; values: Array<{ value: number }> }> }>(
      `${GRAPH}/${postId}/insights?metric=plays,reach`,
      { token: accessToken },
    );
    const plays = res.data.find((m) => m.name === "plays")?.values[0]?.value ?? 0;
    return { platform: "instagram", views: plays, watch_time_s: 0, retention_pct: 0 };
  }
}
