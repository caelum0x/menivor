import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChannelLink } from "./ChannelLink";
import { ottAccessLive, ottCmsLive, ottEmbedLive, ottEnabled, ottStorefrontLive } from "./flags";

describe("OTT web flags", () => {
  it("are off unless the master and the surface flag are both on", () => {
    expect(ottEnabled(undefined)).toBe(false);
    expect(ottStorefrontLive("1", undefined)).toBe(false);
    expect(ottStorefrontLive(undefined, "1")).toBe(false);
    expect(ottStorefrontLive("true", "on")).toBe(true);
    expect(ottEmbedLive("1", "0")).toBe(false);
    expect(ottCmsLive("yes", "1")).toBe(true);
    expect(ottAccessLive("0", "1")).toBe(false);
  });
});

describe("ChannelLink", () => {
  it("renders nothing while the storefront is off", () => {
    const { container } = render(<ChannelLink handle="maya" live={false} />);
    expect(container.innerHTML).toBe("");
  });

  it("links the storefront when live", () => {
    render(<ChannelLink handle="@maya" live />);
    expect(screen.getByRole("link", { name: /watch the channel/i }).getAttribute("href")).toBe("/c/maya");
  });
});
