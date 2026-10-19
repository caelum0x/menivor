/**
 * TikTok Content Posting API adapter (PULL_FROM_URL). Real request shapes; the
 * token is injected per call. No native scheduling → the ReelForge queue owns
 * it. Mirrors the backend `publishing/connectors/tiktok.py`.
 */

import { capsFor, type PlatformCaps } from "../caps.js";
import { httpJson, type HttpOptions } from "../http.js";
import type { AnalyticsSnapshot, Publisher, PublishRequest, PublishResult } from "../publisher.js";

const BASE = "https://open.tiktokapis.com/v2";

export class TikTokPublisher implements Publisher {
  readonly platform = "tiktok" as const;
  constructor(private readonly http: <T>(u: string, o?: HttpOptions) => Promise<T> = httpJson) {}

  caps(): PlatformCaps {
    return capsFor("tiktok")!;
  }
  scheduleSupported(): boolean {
    return false; // no native scheduling → ReelForge queue
  }

  async publish(req: PublishRequest, token: string): Promise<PublishResult> {
    const body = {
      post_info: {
        title: req.caption.slice(0, this.caps().caption_max),
        privacy_level: "SELF_ONLY",
        disable_comment: false,
      },
      source_info: {
        source: "PULL_FROM_URL",
        video_url: req.videoUrl,
      },
    };
    const res = await this.http<{ data: { publish_id: string } }>(
      `${BASE}/post/publish/video/init/`,
      { method: "POST", body, token },
    );
    const publishId = res.data.publish_id;
    return { platform: "tiktok", postId: publishId, url: `https://www.tiktok.com/@me/video/${publishId}` };
  }

  async refresh(refreshToken: string): Promise<{ accessToken: string; expiresIn: number }> {
    const res = await this.http<{ access_token: string; expires_in: number }>(
      `${BASE}/oauth/token/`,
      { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: { grant_type: "refresh_token", refresh_token: refreshToken } },
    );
    return { accessToken: res.access_token, expiresIn: res.expires_in };
  }

  async fetchAnalytics(postId: string, token: string): Promise<AnalyticsSnapshot> {
    const res = await this.http<{ data: { videos: Array<{ view_count?: number; average_watch_time?: number }> } }>(
      `${BASE}/video/query/?fields=view_count,average_watch_time`,
      { method: "POST", body: { filters: { video_ids: [postId] } }, token },
    );
    const v = res.data.videos[0] ?? {};
    return {
      platform: "tiktok",
      views: v.view_count ?? 0,
      watch_time_s: v.average_watch_time ?? 0,
      retention_pct: 0,
    };
  }
}
