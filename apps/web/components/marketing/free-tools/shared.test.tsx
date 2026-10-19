import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CopyButton, copyText } from "./shared";

/**
 * Regression coverage for the free-tools CopyButton: the real production
 * bug (found live on https://menivor.com/tools/tiktok-hook-generator) is
 * that `navigator.clipboard.writeText` throws `NotAllowedError` in several
 * real contexts — webviews/iframes with no clipboard-write permission
 * (including the TikTok and Instagram in-app browsers, a realistic source
 * of traffic for these pages), locked-down permissions policies, and some
 * non-Chromium browsers. The old implementation swallowed that error
 * silently and reset to the idle "Copy" label, so a visitor had zero signal
 * that copying — the entire point of a "generate then copy" tool — failed.
 */

// jsdom does not implement the legacy `execCommand` API at all (unlike a real
// browser), so it must be stubbed directly rather than spied on.
const originalExecCommand = document.execCommand;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.execCommand = originalExecCommand;
});

describe("copyText", () => {
  it("uses the async Clipboard API when it succeeds", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    await expect(copyText("hello")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
  });

  it("falls back to execCommand when the Clipboard API throws (the production bug)", async () => {
    const writeText = vi.fn().mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const execCommand = vi.fn().mockReturnValue(true);
    document.execCommand = execCommand;
    await expect(copyText("hello")).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("falls back to execCommand when the Clipboard API is absent", async () => {
    vi.stubGlobal("navigator", {});
    const execCommand = vi.fn().mockReturnValue(true);
    document.execCommand = execCommand;
    await expect(copyText("hello")).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("reports real failure instead of pretending to succeed when both paths fail", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    document.execCommand = vi.fn().mockReturnValue(false);
    await expect(copyText("hello")).resolves.toBe(false);
  });
});

describe("CopyButton", () => {
  it("shows a real failure state instead of silently resetting to idle", async () => {
    const writeText = vi.fn().mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    document.execCommand = vi.fn().mockReturnValue(false);

    render(<CopyButton text="hello" />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(screen.getByRole("button")).toHaveTextContent("Couldn't copy"));
  });

  it("shows the copied confirmation on success", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    render(<CopyButton text="hello" />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(screen.getByRole("button")).toHaveTextContent("Copied"));
  });
});
