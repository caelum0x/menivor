import { describe, expect, it } from "vitest";
import {
  classifyAsset,
  pickRelease,
  platformFromUserAgent,
  primaryAsset,
  type EditorRelease,
} from "@/lib/editor-releases";

describe("editor releases", () => {
  it("classifies installers and skips checksums", () => {
    expect(
      classifyAsset({ name: "Chop-0.2.3-macos-arm64.dmg", browser_download_url: "https://x/a.dmg", size: 1 }),
    ).toMatchObject({ platform: "macos", label: "macOS (Apple silicon)", format: "dmg" });
    expect(
      classifyAsset({ name: "Chop-windows-x86_64-setup.exe", browser_download_url: "https://x/b.exe" }),
    ).toMatchObject({ platform: "windows", format: "setup.exe" });
    expect(classifyAsset({ name: "SHA256SUMS", browser_download_url: "https://x/s" })).toBeNull();
  });

  it("picks the newest non-draft release with installers, including pre-releases", () => {
    const release = pickRelease([
      { tag_name: "v1-draft", draft: true, assets: [{ name: "a.dmg", browser_download_url: "https://x/a.dmg" }] },
      { tag_name: "v0.3.0-alpha.2", prerelease: true, assets: [{ name: "notes.txt", browser_download_url: "https://x/n" }] },
      { tag_name: "v0.3.0-alpha.1", prerelease: true, assets: [{ name: "a.AppImage", browser_download_url: "https://x/a.AppImage" }] },
    ]);
    expect(release?.tag).toBe("v0.3.0-alpha.1");
    expect(release?.prerelease).toBe(true);
    expect(pickRelease([])).toBeNull();
  });

  it("reads the visitor's desktop OS from the user agent", () => {
    expect(platformFromUserAgent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")).toBe("macos");
    expect(platformFromUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("windows");
    expect(platformFromUserAgent("Mozilla/5.0 (X11; Linux x86_64)")).toBe("linux");
    expect(platformFromUserAgent("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)")).toBeNull();
    expect(platformFromUserAgent(null)).toBeNull();
  });

  it("offers one installer: the visitor's platform first, Apple silicon first", () => {
    const release = pickRelease([
      {
        tag_name: "v1",
        assets: [
          { name: "Chop_x64.dmg", browser_download_url: "https://x/intel.dmg" },
          { name: "Chop_aarch64.dmg", browser_download_url: "https://x/arm.dmg" },
          { name: "Chop_x64.msi", browser_download_url: "https://x/a.msi" },
          { name: "Chop_x64-setup.exe", browser_download_url: "https://x/a-setup.exe" },
        ],
      },
    ]) as EditorRelease;
    expect(primaryAsset(release, "macos")?.url).toBe("https://x/arm.dmg");
    expect(primaryAsset(release, "windows")?.url).toBe("https://x/a-setup.exe");
    expect(primaryAsset(release, "linux")?.platform).toBe("macos");
    expect(primaryAsset(release, null)?.platform).toBe("macos");
  });
});
