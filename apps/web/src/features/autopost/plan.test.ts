import { describe, expect, it } from "vitest";

import { formatHours, parseHours } from "./AccountPace";
import type { CreatorInfo } from "./api";
import {
  EMPTY_FORM,
  HOOK_STYLES,
  allowedVisibilities,
  buildCampaignBody,
  consentText,
  interactionLocks,
  parseHashtags,
  statusText,
  variationHooks,
} from "./plan";
import { inView } from "./QueueScreen";

const info = (over: Partial<CreatorInfo> = {}): CreatorInfo => ({
  nickname: "Shop",
  username: "shop",
  avatar_url: "",
  privacy_level_options: ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
  comment_disabled: false,
  duet_disabled: false,
  stitch_disabled: false,
  max_video_post_duration_sec: 600,
  audited: true,
  ...over,
});

const ready = {
  ...EMPTY_FORM,
  jobIds: ["j1", "j1", "j2"],
  accountIds: ["a1"],
  visibility: "public" as const,
  consent: true,
};

describe("autopost plan", () => {
  it("gives each variation a different hook and caps at the available angles", () => {
    expect(variationHooks(3)).toEqual(["pov", "question", "nobody_tells_you"]);
    expect(variationHooks(50)).toHaveLength(HOOK_STYLES.length);
    expect(new Set(variationHooks(50)).size).toBe(HOOK_STYLES.length);
  });

  it("limits visibility to what every TikTok account allows", () => {
    expect(allowedVisibilities([])).toEqual(["public", "friends", "private"]);
    expect(allowedVisibilities([info(), info({ privacy_level_options: ["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS"] })]))
      .toEqual(["friends", "private"]);
    expect(allowedVisibilities([info({ audited: false })])).toEqual(["private"]);
  });

  it("locks an interaction off when any account has it off", () => {
    expect(interactionLocks([info(), info({ duet_disabled: true })])).toEqual({
      comments: false,
      duet: true,
      stitch: false,
    });
  });

  it("uses TikTok's declaration wording", () => {
    expect(consentText(false, true)).toContain("TikTok's Music Usage Confirmation.");
    expect(consentText(true, true)).toContain("Branded Content Policy and Music Usage Confirmation");
    expect(consentText(false, false)).not.toContain("TikTok");
  });

  it("builds the request and refuses incomplete forms", () => {
    const body = buildCampaignBody({ ...ready, hashtags: "#shop, deals deals", commercial: true, yourBrand: true });
    expect(body.job_ids).toEqual(["j1", "j2"]);
    expect(body.hashtags).toEqual(["shop", "deals"]);
    expect(body.brand_organic).toBe(true);
    expect(body.brand_content).toBe(false);
    expect(body.allow_comments).toBe(false);
    expect(() => buildCampaignBody({ ...ready, visibility: "" })).toThrow(/who can see/);
    expect(() => buildCampaignBody({ ...ready, consent: false })).toThrow(/Confirm/);
    expect(() => buildCampaignBody({ ...ready, commercial: true })).toThrow(/brand/);
    expect(() =>
      buildCampaignBody({ ...ready, visibility: "private", commercial: true, brandedContent: true }),
    ).toThrow(/cannot be private/);
    expect(() => buildCampaignBody({ ...ready, startAt: "2000-01-01T00:00" })).toThrow(/past/);
  });

  it("parses hashtags and posting hours", () => {
    expect(parseHashtags("#a #a b,c")).toEqual(["a", "b", "c"]);
    expect(parseHours("9-11, 18")).toEqual([9, 10, 11, 18]);
    expect(formatHours([9, 10, 11, 18])).toBe("9-11, 18");
    expect(() => parseHours("22-25")).toThrow();
  });

  it("describes queue states plainly", () => {
    expect(statusText({ status: "scheduled", provider_status: "waiting:daily_cap" })).toBe(
      "Waiting for the account's posting limit",
    );
    expect(statusText({ status: "published", provider_status: "SEND_TO_USER_INBOX" })).toBe(
      "Sent to TikTok drafts",
    );
    const post = { status: "held" } as Parameters<typeof inView>[0];
    expect(inView(post, "attention")).toBe(true);
    expect(inView(post, "upcoming")).toBe(false);
  });
});
