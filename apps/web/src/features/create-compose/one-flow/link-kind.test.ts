import { describe, expect, it } from "vitest";
import { detectLinkKind } from "./link-kind";

const CASES: ReadonlyArray<readonly [string, string, string | null, string]> = [
  ["https://www.tiktok.com/@mrbeast/video/7300000000000000000", "social_post", "tiktok", "TikTok post detected"],
  ["https://vm.tiktok.com/ZMabc123/", "social_post", "tiktok", "TikTok post detected"],
  ["https://www.tiktok.com/@mrbeast", "social_profile", "tiktok", "TikTok profile detected"],
  ["https://www.instagram.com/reel/C1abcDEF/", "social_post", "instagram", "Instagram post detected"],
  ["https://www.instagram.com/p/C1abcDEF/", "social_post", "instagram", "Instagram post detected"],
  ["https://www.instagram.com/nike/", "social_profile", "instagram", "Instagram profile detected"],
  ["https://www.instagram.com/explore/", "website", null, "Website detected"],
  ["https://x.com/jack/status/20", "social_post", "x", "X post detected"],
  ["https://twitter.com/jack", "social_profile", "x", "X profile detected"],
  ["https://x.com/home", "website", null, "Website detected"],
  ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "social_post", "youtube", "YouTube video detected"],
  ["https://youtu.be/dQw4w9WgXcQ", "social_post", "youtube", "YouTube video detected"],
  ["https://www.youtube.com/shorts/abc123", "social_post", "youtube", "YouTube Short detected"],
  ["https://www.youtube.com/@mkbhd", "social_profile", "youtube", "YouTube channel detected"],
  ["https://www.youtube.com/channel/UC123", "social_profile", "youtube", "YouTube channel detected"],
  ["https://m.youtube.com/watch?v=abc", "social_post", "youtube", "YouTube video detected"],
  ["https://www.facebook.com/nike/videos/123456/", "social_post", "facebook", "Facebook post detected"],
  ["https://fb.watch/abc/", "social_post", "facebook", "Facebook post detected"],
  ["https://www.facebook.com/nike", "social_profile", "facebook", "Facebook profile detected"],
  ["https://www.threads.net/@zuck/post/C1abc", "social_post", "threads", "Threads post detected"],
  ["https://www.threads.com/@zuck", "social_profile", "threads", "Threads profile detected"],
  ["https://www.pinterest.com/pin/123456789/", "social_post", "pinterest", "Pinterest pin detected"],
  ["https://pin.it/abc", "social_post", "pinterest", "Pinterest pin detected"],
  ["https://uk.pinterest.co.uk/marthastewart/", "social_profile", "pinterest", "Pinterest profile detected"],
  ["https://www.linkedin.com/posts/satya_activity-123", "social_post", "linkedin", "LinkedIn post detected"],
  ["https://www.linkedin.com/in/satyanadella/", "social_profile", "linkedin", "LinkedIn profile detected"],
  ["https://www.linkedin.com/company/microsoft/", "social_profile", "linkedin", "LinkedIn page detected"],
  ["https://apps.apple.com/us/app/notion/id1232780281", "app_store", null, "App Store app detected"],
  ["https://play.google.com/store/apps/details?id=com.spotify.music", "play_store", null, "Google Play app detected"],
  ["https://yourshop.com/products/mug", "website", null, "Website detected"],
  ["https://nottiktok.com/@x/video/1", "website", null, "Website detected"],
];

describe("detectLinkKind", () => {
  it.each(CASES)("%s", (url, kind, platform, label) => {
    expect(detectLinkKind(url)).toEqual({ kind, platform, label });
  });

  it("treats unparsable input as a website", () => {
    expect(detectLinkKind("not a url").kind).toBe("website");
  });
});
