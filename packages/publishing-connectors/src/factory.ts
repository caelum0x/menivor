/** Resolve a Publisher for a platform (all stateless; tokens passed per call). */
import type { Platform } from "./caps.js";
import type { Publisher } from "./publisher.js";
import { TikTokPublisher } from "./tiktok/client.js";
import { InstagramPublisher } from "./instagram/client.js";
import { YouTubePublisher } from "./youtube/client.js";
import { XPublisher } from "./x/client.js";

export function createPublisher(platform: Platform): Publisher {
  switch (platform) {
    case "tiktok": return new TikTokPublisher();
    case "instagram": return new InstagramPublisher();
    case "youtube": return new YouTubePublisher();
    case "x": return new XPublisher();
  }
}
