import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { EMPTY_FORM } from "./plan";
import { DetailsStep } from "./wizard/DetailsStep";

afterEach(cleanup);

const creator = {
  accountId: "a1",
  error: "",
  info: {
    nickname: "Glow Shop",
    username: "glowshop",
    avatar_url: "",
    privacy_level_options: ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
    comment_disabled: true,
    duet_disabled: false,
    stitch_disabled: false,
    max_video_post_duration_sec: 600,
    audited: true,
  },
};

describe("DetailsStep (TikTok posting rules)", () => {
  it("shows the creator, has no default visibility, and starts every interaction off", () => {
    const onChange = vi.fn();
    render(<DetailsStep form={EMPTY_FORM} onChange={onChange} tiktok={[creator]} />);
    expect(screen.getByText("Glow Shop")).toBeTruthy();
    const visibility = screen.getByLabelText("Who can see the posts") as HTMLSelectElement;
    expect(visibility.value).toBe("");
    expect(Array.from(visibility.options).map((o) => o.textContent)).toEqual(["Choose", "Everyone", "Only me"]);
    const comments = screen.getByLabelText(/Allow comments/) as HTMLInputElement;
    expect(comments.disabled).toBe(true);
    expect((screen.getByLabelText(/Allow Duet/) as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText(/TikTok's Music Usage Confirmation/)).toBeTruthy();
    expect(screen.getByText(/labelled as AI-generated/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/commercial content/));
    expect(onChange).toHaveBeenCalledWith({ commercial: true, yourBrand: false, brandedContent: false });
  });

  it("leaves TikTok wording out when no TikTok account is chosen", () => {
    render(<DetailsStep form={EMPTY_FORM} onChange={vi.fn()} tiktok={[]} />);
    expect(screen.queryByText(/TikTok's Music Usage/)).toBeNull();
    expect(screen.queryByText("On TikTok")).toBeNull();
  });
});
