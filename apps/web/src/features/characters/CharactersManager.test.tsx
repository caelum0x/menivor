import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { CharactersManager } from "./CharactersManager";

const getToken = async () => "tok";
const auth = { getToken, isLoaded: true };
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => auth,
  UserButton: () => null,
}));

function jsonResponse(
  body: unknown,
  init: { ok?: boolean; status?: number } = {},
): Response {
  const ok = init.ok ?? true;
  return {
    ok,
    status: init.status ?? (ok ? 200 : 400),
    statusText: ok ? "OK" : "Error",
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const NOVA = {
  id: "char-1",
  name: "Nova",
  descriptors: ["silver hair"],
  reference_images: [],
  style: "3D pixar",
  lora_ref: "",
  identity_key: "abc123def456",
};

const LIST = { status: 200, data: { characters: [NOVA] } };
const EMPTY = { status: 200, data: { characters: [] } };

describe("CharactersManager", () => {
  it("loads characters from GET /characters and renders them", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(LIST));
    vi.stubGlobal("fetch", fetchMock);

    render(<CharactersManager />);

    await waitFor(() => expect(screen.getByText("Nova")).toBeInTheDocument());
    expect(String(fetchMock.mock.calls[0]![0])).toContain("/characters");
  });

  it("deletes a character via DELETE /characters/{id} and reloads", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(LIST)) // initial list
      .mockResolvedValueOnce(
        jsonResponse({ status: 200, data: { deleted: true, id: "char-1" } }),
      ) // delete
      .mockResolvedValueOnce(jsonResponse(EMPTY)); // reload
    vi.stubGlobal("fetch", fetchMock);

    render(<CharactersManager />);
    await waitFor(() => expect(screen.getByText("Nova")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /delete nova/i }));

    await waitFor(() =>
      expect(screen.getByText(/no characters yet/i)).toBeInTheDocument(),
    );

    const deleteCall = fetchMock.mock.calls.find(
      (c) => c[1]?.method === "DELETE",
    );
    expect(deleteCall).toBeTruthy();
    expect(String(deleteCall?.[0])).toContain("/characters/char-1");
  });

  it("opens a character (GET /characters/{id}) and generates a shot prompt (POST)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(LIST)) // initial list
      .mockResolvedValueOnce(jsonResponse({ status: 200, data: NOVA })) // getCharacter
      .mockResolvedValueOnce(
        jsonResponse({
          status: 200,
          data: {
            prompt: "Nova sipping coffee, silver hair",
            negative_prompt: "blurry",
            seed: 42,
            reference_images: [],
            lora_ref: "",
          },
        }),
      ); // shot-prompt
    vi.stubGlobal("fetch", fetchMock);

    render(<CharactersManager />);
    await waitFor(() => expect(screen.getByText("Nova")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Nova" }));

    await waitFor(() =>
      expect(screen.getByText(/shot prompt · nova/i)).toBeInTheDocument(),
    );

    fireEvent.change(
      screen.getByPlaceholderText(/action/i),
      { target: { value: "sipping coffee" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /generate locked shot/i }));

    await waitFor(() =>
      expect(screen.getByText(/Nova sipping coffee/i)).toBeInTheDocument(),
    );

    const getCall = fetchMock.mock.calls.find(
      (c) => c[1]?.method === "GET" && String(c[0]).includes("/characters/char-1"),
    );
    expect(getCall).toBeTruthy();
    const shotCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/characters/char-1/shot-prompt"),
    );
    expect(shotCall?.[1]?.method).toBe("POST");
    expect(JSON.parse(shotCall?.[1]?.body as string).action).toBe("sipping coffee");
  });
});
