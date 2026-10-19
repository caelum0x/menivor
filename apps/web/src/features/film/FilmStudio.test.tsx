import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { FilmStudio } from "./FilmStudio";

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
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const CREATE_RESULT = {
  status: 200,
  data: {
    id: "proj-1",
    title: "Midnight Courier",
    status: "planned",
    shot_count: 1,
    total_runtime_s: 3.2,
  },
};

const PROJECT_DETAIL = {
  status: 200,
  data: {
    id: "proj-1",
    title: "Midnight Courier",
    status: "planned",
    total_runtime_s: 3.2,
    shots: [
      {
        shot_id: "shot_1",
        order: 1,
        role: "establishing",
        camera_motion: "static",
        duration_ms: 3200,
        prompt: "Mara, red coat, wakes to a ringing phone",
        seed: 42,
        status: "pending",
      },
    ],
  },
};

function fillForm() {
  fireEvent.change(screen.getByPlaceholderText(/Midnight Courier/i), {
    target: { value: "Midnight Courier" },
  });
  fireEvent.change(screen.getByPlaceholderText(/e\.g\. Mara/i), {
    target: { value: "Mara" },
  });
  fireEvent.change(
    screen.getByPlaceholderText(/Mara wakes to a ringing phone/i),
    { target: { value: "s1 | Mara wakes to a ringing phone" } },
  );
}

describe("FilmStudio", () => {
  it("creates a project (POST + Idempotency-Key) then loads its shots (GET)", async () => {
    type Init = { method?: string; headers: Record<string, string>; body?: string };
    const fetchMock = vi.fn(async (url: string, init: Init) => {
      if (String(url).includes("/film/projects?")) {
        return jsonResponse({ status: 200, data: { projects: [] } }); // list
      }
      if (init.method === "POST") return jsonResponse(CREATE_RESULT); // create
      return jsonResponse(PROJECT_DETAIL); // GET /film/projects/proj-1
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<FilmStudio />);
    await waitFor(() => expect(screen.getByText(/no films yet/i)).toBeInTheDocument());
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /create project/i }));

    // Persisted project opens with its runtime summary.
    await waitFor(() =>
      expect(screen.getByText(/1 shots · 3\.2s runtime/i)).toBeInTheDocument(),
    );

    const createCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).endsWith("/film/projects") && c[1]?.method === "POST",
    );
    expect(createCall).toBeTruthy();
    expect(createCall![1].method).toBe("POST");
    expect(createCall![1].headers["Idempotency-Key"]).toBeTruthy();
    const sentBody = JSON.parse(createCall![1].body ?? "{}");
    expect(sentBody.title).toBe("Midnight Courier");
    expect(sentBody.beats).toEqual([
      { scene_id: "s1", summary: "Mara wakes to a ringing phone" },
    ]);
    expect(sentBody.character.character_id).toBe("mara");

    // Detail fetched via GET /film/projects/{id} and its shot rendered.
    const getCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/film/projects/proj-1"),
    );
    expect(getCall).toBeTruthy();
    expect(getCall![1].method).toBe("GET");
    await waitFor(() =>
      expect(
        screen.getByText(/Mara, red coat, wakes to a ringing phone/i),
      ).toBeInTheDocument(),
    );
  });

  it("requires at least one beat before creating", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ status: 200, data: { projects: [] } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<FilmStudio />);
    await waitFor(() => expect(screen.getByText(/no films yet/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /create project/i }));

    await waitFor(() =>
      expect(screen.getByText(/add at least one beat/i)).toBeInTheDocument(),
    );
    expect(
      fetchMock.mock.calls.some((c) => (c as unknown[])[1] && ((c as unknown[])[1] as { method?: string }).method === "POST"),
    ).toBe(false);
  });

  it("surfaces a create error from the API", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: { method?: string }) =>
      init?.method === "POST"
        ? jsonResponse(
            { message: "film persistence unavailable" },
            { ok: false, status: 503 },
          )
        : jsonResponse({ status: 200, data: { projects: [] } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<FilmStudio />);
    await waitFor(() => expect(screen.getByText(/no films yet/i)).toBeInTheDocument());
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /create project/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/went wrong on our side/i),
      ).toBeInTheDocument(),
    );
  });
});
