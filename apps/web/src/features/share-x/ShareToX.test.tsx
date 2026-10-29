import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "@/lib/i18n/context";
import { ShareToX } from "./ShareToX";

describe("ShareToX", () => {
  it("links to the X composer and tells the viewer to attach the MP4", () => {
    render(
      <ShareToX
        hook="Stop scrolling."
        sourceUrl="https://shop.example/mug"
        downloadUrl="https://cdn.example/reel.mp4"
        downloadFilename="menivor-reel.mp4"
      />,
    );

    const link = screen.getByRole("link", { name: /share to x/i });
    expect(link.getAttribute("href")).toContain("https://x.com/intent/post?");
    expect(link.getAttribute("href")).toContain(encodeURIComponent("Stop scrolling."));
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(screen.getByText(/download the mp4/i)).toBeInTheDocument();
  });

  it("downloads the MP4 before the composer opens", () => {
    const clicks: string[] = [];
    const original = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function click(this: HTMLAnchorElement) {
      clicks.push(this.getAttribute("download") ?? "");
    };
    try {
      render(
        <ShareToX
          hook="Hi"
          downloadUrl="https://cdn.example/reel.mp4"
          downloadFilename="menivor-reel.mp4"
        />,
      );
      fireEvent.click(screen.getByRole("link", { name: /share to x/i }));
    } finally {
      HTMLAnchorElement.prototype.click = original;
    }

    expect(clicks).toContain("menivor-reel.mp4");
    expect(document.querySelector('iframe[name="menivor-share-x-download"]')).not.toBeNull();
  });

  it("shows the Turkish hint when the locale is Turkish", () => {
    render(
      <I18nProvider initialLocale="tr">
        <ShareToX hook="Merhaba" sourceUrl="https://shop.example/urun" />
      </I18nProvider>,
    );

    expect(screen.getByRole("link", { name: /x'te paylaş/i })).toBeInTheDocument();
    expect(screen.getByText(/MP4'ü indir/)).toBeInTheDocument();
  });
});
