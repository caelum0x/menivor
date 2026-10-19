import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CredentialsCheck } from "./CredentialsCheck";

function pick(file: File) {
  const input = screen.getByLabelText("MP4 video") as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

const mp4 = () => new File([new Uint8Array([0, 0, 0, 24])], "reel.mp4", { type: "video/mp4" });

afterEach(() => vi.unstubAllGlobals());

describe("CredentialsCheck (M7.1)", () => {
  it("uploads the file and shows the signed Menivor result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 200,
          data: {
            present: true,
            valid: true,
            trusted: false,
            ai_generated: true,
            made_with_menivor: true,
            content_id: "job42",
            signer: "Menivor Content Credentials",
            verdict: "Signed by Menivor and marked as AI-generated. The signature is valid.",
          },
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<CredentialsCheck />);
    pick(mp4());
    await screen.findByText("Signed by Menivor and marked as AI-generated. The signature is valid.");
    const [url, init] = fetchMock.mock.calls[0] as [RequestInfo, RequestInit];
    expect(String(url)).toMatch(/\/legal\/content-credentials$/);
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
    expect(screen.getByText("job42")).toBeTruthy();
    expect(screen.getByText("Signer on the C2PA trust list").nextSibling?.textContent).toBe("No");
  });

  it("shows the no-credentials verdict without detail rows", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: 200,
            data: {
              present: false, valid: false, trusted: false, ai_generated: false,
              made_with_menivor: false, content_id: null,
              verdict: "No Content Credentials found in this file.",
            },
          }),
          { status: 200 },
        ),
      ),
    );
    render(<CredentialsCheck />);
    pick(mp4());
    await screen.findByText("No Content Credentials found in this file.");
    expect(screen.queryByText("Signature")).toBeNull();
  });

  it("explains rate limits and refused files", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 429 })));
    render(<CredentialsCheck />);
    pick(mp4());
    await screen.findByText("Too many checks from here. Try again in an hour.");
  });

  it("refuses a file over the size cap before uploading", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<CredentialsCheck />);
    const big = mp4();
    Object.defineProperty(big, "size", { value: 201 * 1024 * 1024 });
    pick(big);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("The video is larger than 200 MB."));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
