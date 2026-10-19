import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { friendlyErrorMessage, isHumanReadable, isSignedOutError } from "./friendly";

describe("friendlyErrorMessage", () => {
  it("hides request ids and header names", () => {
    const err = new ApiError("2e2bc772a1f94c0e: missing x-api-key header", 400);
    expect(friendlyErrorMessage(err)).toBe("Something went wrong. Please try again.");
  });

  it("maps signed-out failures to a sign-in sentence", () => {
    const err = new ApiError("Your session expired.", 401, undefined, "abc12345def");
    expect(friendlyErrorMessage(err)).toBe("Please sign in to continue.");
    expect(isSignedOutError(err)).toBe(true);
  });

  it("keeps plain validation sentences", () => {
    const err = new ApiError("Enter a valid product link.", 422);
    expect(friendlyErrorMessage(err)).toBe("Enter a valid product link.");
  });

  it("strips the correlation suffix before judging", () => {
    const err = new ApiError("That project is already publishing.", 409, undefined, "c0ffee1234");
    expect(friendlyErrorMessage(err)).toBe("That project is already publishing.");
  });

  it("keeps a plain 4xx sentence after dropping the request-id prefix", () => {
    const err = new ApiError("2e2bc772a1f94c0e2e2bc772a1f94c0e: Insufficient balance for this transfer.", 402);
    expect(friendlyErrorMessage(err)).toBe("Insufficient balance for this transfer.");
  });

  it("maps server and network failures", () => {
    expect(friendlyErrorMessage(new ApiError("boom", 500))).toMatch(/our side/);
    expect(friendlyErrorMessage(new ApiError("Network error contacting the API: x", 0))).toMatch(/connection/);
  });

  it("never shows raw technical Error text", () => {
    expect(friendlyErrorMessage(new TypeError("Cannot read properties of undefined"), "Nope.")).toBe("Nope.");
    expect(friendlyErrorMessage(new Error("Request failed with status 404 Not Found"), "Nope.")).toBe("Nope.");
    expect(friendlyErrorMessage({ weird: true }, "Nope.")).toBe("Nope.");
  });

  it("judges readability", () => {
    expect(isHumanReadable("Recipient handle not found.")).toBe(true);
    expect(isHumanReadable("invalid_grant")).toBe(false);
    expect(isHumanReadable('{"error":"x"}')).toBe(false);
  });
});
