/**
 * YouTube Data API adapter — resumable upload + Shorts metadata. The resumable
 * PUT is executed by the API layer (streams from R2); this returns the request
 * shapes. Mirrors `publishing/connectors/youtube.py`.
 */
import { capsFor, type PlatformCaps } from "../caps.js";
import { httpJson, type HttpOptions } from "../http.js";
import type { AnalyticsSnapshot, Publisher, PublishRequest, PublishResult } from "../publisher.js";

const API = "https://www.googleapis.com/youtube/v3";
const UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos";

export class YouTubePublisher implements Publisher {
  readonly platform = "youtube" as const;
  constructor(private readonly http: <T>(u: string, o?: HttpOptions) => Promise<T> = httpJson) {}

  caps(): PlatformCaps { return capsFor("youtube")!; }
  scheduleSupported(): boolean { return true; } // publishAt

  /** Initiate a resumable upload; returns the upload session URL as the postId hint. */
  async publish(req: PublishRequest, token: string): Promise<PublishResult> {
    const snippet = {
      snippet: { title: req.caption.slice(0, this.caps().caption_max) || "Short", categoryId: "22" },
      status: { privacyStatus: "private", selfDeclaredMadeForKids: false },
    };
    // Real init returns the resumable session in the Location header; the API layer
    // PUTs the bytes there. We return the inserted resource once complete.
    const res = await this.http<{ id: string }>(
      `${UPLOAD}?uploadType=resumable&part=snippet,status`,
      { method: "POST", token, headers: { "X-Upload-Content-Type": "video/mp4" }, body: snippet },
    );
    return { platform: "youtube", postId: res.id, url: `https://youtube.com/shorts/${res.id}` };
  }

  async refresh(refreshToken: string): Promise<{ accessToken: string; expiresIn: number }> {
    const res = await this.http<{ access_token: string; expires_in: number }>(
      "https://oauth2.googleapis.com/token",
      { method: "POST", body: { grant_type: "refresh_token", refresh_token: refreshToken } },
    );
    return { accessToken: res.access_token, expiresIn: res.expires_in };
  }

  async fetchAnalytics(postId: string, token: string): Promise<AnalyticsSnapshot> {
    const res = await this.http<{ items: Array<{ statistics: { viewCount?: string } }> }>(
      `${API}/videos?part=statistics&id=${encodeURIComponent(postId)}`,
      { token },
    );
    const views = Number(res.items[0]?.statistics.viewCount ?? 0);
    return { platform: "youtube", views, watch_time_s: 0, retention_pct: 0 };
  }
}
