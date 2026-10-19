/**
 * X (Twitter) API v2 adapter — pay-per-use posting. Media upload is 2-step
 * (upload → create tweet). Usage note ($0.015/post) is surfaced for wallet
 * metering by the API layer. Mirrors the backend X connector.
 */
import { capsFor, type PlatformCaps } from "../caps.js";
import { httpJson, type HttpOptions } from "../http.js";
import type { AnalyticsSnapshot, Publisher, PublishRequest, PublishResult } from "../publisher.js";

const API = "https://api.twitter.com/2";

/** Per-post cost in integer microdollars (for wallet metering). */
export const X_POST_COST_MICROS = 15_000; // $0.015

export class XPublisher implements Publisher {
  readonly platform = "x" as const;
  constructor(private readonly http: <T>(u: string, o?: HttpOptions) => Promise<T> = httpJson) {}

  caps(): PlatformCaps { return capsFor("x")!; }
  scheduleSupported(): boolean { return false; }

  /** `token` carries the uploaded media id as `${mediaId}:${accessToken}`. */
  async publish(req: PublishRequest, token: string): Promise<PublishResult> {
    const [mediaId, accessToken] = token.split(":");
    const res = await this.http<{ data: { id: string } }>(
      `${API}/tweets`,
      { method: "POST", token: accessToken,
        body: { text: req.caption.slice(0, this.caps().caption_max), media: { media_ids: [mediaId] } } },
    );
    return { platform: "x", postId: res.data.id, url: `https://x.com/i/status/${res.data.id}` };
  }

  async refresh(refreshToken: string): Promise<{ accessToken: string; expiresIn: number }> {
    const res = await this.http<{ access_token: string; expires_in: number }>(
      `${API}/oauth2/token`,
      { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: { grant_type: "refresh_token", refresh_token: refreshToken } },
    );
    return { accessToken: res.access_token, expiresIn: res.expires_in };
  }

  async fetchAnalytics(postId: string, token: string): Promise<AnalyticsSnapshot> {
    const [, accessToken] = token.split(":");
    const res = await this.http<{ data: { public_metrics?: { impression_count?: number } } }>(
      `${API}/tweets/${encodeURIComponent(postId)}?tweet.fields=public_metrics`,
      { token: accessToken },
    );
    return { platform: "x", views: res.data.public_metrics?.impression_count ?? 0, watch_time_s: 0, retention_pct: 0 };
  }
}
