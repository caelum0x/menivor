import { describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => null }) }));

import { ApiError } from "@/src/shared/api";
import { retryErrorMessage } from "./VariantResults";

describe("retryErrorMessage", () => {
  it("names a locked format instead of blaming the balance", () => {
    const err = new ApiError("req: This format is not available yet", 402, {
      status: 402,
      data: { code: "format_locked", format: "generated_script", reason: "no script LLM is configured" },
    });
    const message = retryErrorMessage(err);
    expect(message).toMatch(/AI-written script is not available on this server yet: no script LLM is configured/);
    expect(message).not.toMatch(/balance/);
  });

  it("keeps the credit message for a real shortfall", () => {
    const err = new ApiError("req: insufficient credits", 402, { status: 402 });
    expect(retryErrorMessage(err)).toBe("Retrying needs 1 credit and your balance is empty.");
  });

  it("passes other errors through", () => {
    expect(retryErrorMessage(new ApiError("Job is not failed", 409))).toBe("Job is not failed");
    expect(retryErrorMessage("x")).toBe("Retry failed.");
  });
});
