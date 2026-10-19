import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const auth = { isLoaded: true, userId: null as string | null };
const getMe = vi.fn();
const adminListUsers = vi.fn();

vi.mock("@/components/auth/clerk-safe", () => ({ useAuth: () => auth }));
vi.mock("@/lib/use-api-token", () => ({
  useApiToken: () => getToken,
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    getMe: (...args: unknown[]) => getMe(...args),
    adminListUsers: (...args: unknown[]) => adminListUsers(...args),
  };
});

const getToken = async () => "jwt";

import { useIsStaff } from "@/components/admin/use-is-staff";

function Probe({ id }: Readonly<{ id: string }>) {
  const { status } = useIsStaff();
  return <p data-testid={id}>{status}</p>;
}

const ME = { user_id: "u", email: "a@b.c", credits: 3, jobs_count: 0 };

describe("useIsStaff", () => {
  beforeEach(() => {
    getMe.mockReset();
    adminListUsers.mockReset();
  });

  it("does not call the API for a signed-out visitor", async () => {
    auth.userId = null;
    render(<Probe id="a" />);
    await waitFor(() => expect(screen.getByTestId("a").textContent).toBe("denied"));
    expect(getMe).not.toHaveBeenCalled();
  });

  it("reads /me once per user and never probes a staff-only endpoint", async () => {
    auth.userId = "user_once";
    getMe.mockResolvedValue({ ...ME, is_staff: false });
    render(
      <>
        <Probe id="a" />
        <Probe id="b" />
      </>,
    );
    await waitFor(() => expect(screen.getByTestId("b").textContent).toBe("denied"));
    expect(screen.getByTestId("a").textContent).toBe("denied");
    expect(getMe).toHaveBeenCalledTimes(1);
    expect(adminListUsers).not.toHaveBeenCalled();
  });

  it("reports staff when /me says so", async () => {
    auth.userId = "user_staff";
    getMe.mockResolvedValue({ ...ME, is_staff: true });
    render(<Probe id="a" />);
    await waitFor(() => expect(screen.getByTestId("a").textContent).toBe("staff"));
  });

  it("fails closed when /me has no flag", async () => {
    auth.userId = "user_old_api";
    getMe.mockResolvedValue(ME);
    render(<Probe id="a" />);
    await waitFor(() => expect(screen.getByTestId("a").textContent).toBe("denied"));
  });
});
