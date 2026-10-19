/**
 * `@reelforge/publishing-connectors` — the shared publish contract + policy.
 *
 * The `Publisher` interface plus the per-platform **caps**, **watermark cross-post
 * rules**, and **OAuth config** — the parts the cap-aware composer (web/mobile)
 * and the publish policy (api) must agree on, byte-identical to the Python port
 * (`reelforge_publishing_connectors`, golden fixtures). Stateless: tokens are
 * passed in per call, never persisted.
 */

export {
  PLATFORMS,
  CAPS,
  capsFor,
  validatePublish,
  remainingDaily,
  type Platform,
  type PlatformCaps,
  type PublishCheck,
} from "./caps.js";
export {
  isWatermarkAllowed,
  checkWatermark,
  type WatermarkCheck,
} from "./watermark-policy.js";
export {
  OAUTH,
  oauthFor,
  scopeString,
  requiresPkce,
  type OAuthConfig,
} from "./oauth-config.js";
export {
  type Publisher,
  type PublishRequest,
  type PublishResult,
  type ConnectorError,
  type AnalyticsSnapshot,
} from "./publisher.js";
export { httpJson, HttpError, type HttpOptions } from "./http.js";
export { TikTokPublisher } from "./tiktok/client.js";
export { InstagramPublisher } from "./instagram/client.js";
export { YouTubePublisher } from "./youtube/client.js";
export { XPublisher, X_POST_COST_MICROS } from "./x/client.js";
export { createPublisher } from "./factory.js";
