/**
 * Email sign-in (one-time code) on Scribase Auth: the Android/any-device path
 * next to Sign in with Apple. Off until the build config turns it on.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";

import {
  EMAIL_CODE_LENGTH,
  isEmailSignInEnabled,
  normalizeEmail,
  normalizeEmailCode,
  requestEmailCode,
  verifyEmailCode,
} from "../email-otp";

const ROOT = path.resolve(__dirname, "../../../..");

function fakeClient(opts: { otpError?: string; verifyError?: string; session?: boolean } = {}) {
  const signInWithOtp = vi.fn(async () => ({
    data: {},
    error: opts.otpError ? { message: opts.otpError } : null,
  }));
  const verifyOtp = vi.fn(async () => ({
    data: { session: opts.session === false ? null : { access_token: "jwt" } },
    error: opts.verifyError ? { message: opts.verifyError } : null,
  }));
  const client = { auth: { signInWithOtp, verifyOtp } } as unknown as SupabaseClient;
  return { client, signInWithOtp, verifyOtp };
}

describe("isEmailSignInEnabled", () => {
  it("is off unless app.json extra.auth.email or the env flag says so", () => {
    expect(isEmailSignInEnabled({}, {})).toBe(false);
    expect(isEmailSignInEnabled({ auth: { email: false } }, {})).toBe(false);
    expect(isEmailSignInEnabled({ auth: { email: "yes" } }, {})).toBe(false);
    expect(isEmailSignInEnabled({ auth: { email: true } }, {})).toBe(true);
    expect(isEmailSignInEnabled({}, { EXPO_PUBLIC_EMAIL_SIGNIN: "1" })).toBe(true);
    expect(isEmailSignInEnabled({}, { EXPO_PUBLIC_EMAIL_SIGNIN: "true" })).toBe(false);
  });
});

describe("email and code input", () => {
  it("normalises a valid email and rejects junk", () => {
    expect(normalizeEmail("  Ada@Example.COM ")).toBe("ada@example.com");
    for (const bad of ["", "ada", "ada@", "@x.io", "a b@x.io", "ada@x"]) {
      expect(normalizeEmail(bad), bad).toBeNull();
    }
  });

  it("accepts only a full numeric code", () => {
    expect(EMAIL_CODE_LENGTH).toBe(6);
    expect(normalizeEmailCode(" 123 456 ")).toBe("123456");
    expect(normalizeEmailCode("12345")).toBeNull();
    expect(normalizeEmailCode("12345a")).toBeNull();
  });
});

describe("requestEmailCode", () => {
  it("asks Scribase for a code and creates the account on first use", async () => {
    const { client, signInWithOtp } = fakeClient();
    await requestEmailCode(client, " Ada@Example.com");
    expect(signInWithOtp).toHaveBeenCalledWith({
      email: "ada@example.com",
      options: { shouldCreateUser: true },
    });
  });

  it("fails fast on a bad email without calling the server", async () => {
    const { client, signInWithOtp } = fakeClient();
    await expect(requestEmailCode(client, "nope")).rejects.toThrow(/valid email/i);
    expect(signInWithOtp).not.toHaveBeenCalled();
  });

  it("surfaces the server error", async () => {
    const { client } = fakeClient({ otpError: "rate limited" });
    await expect(requestEmailCode(client, "a@b.io")).rejects.toThrow(/rate limited/);
  });

  it("explains a missing auth project", async () => {
    await expect(requestEmailCode(null, "a@b.io")).rejects.toThrow(/not available/i);
  });
});

describe("verifyEmailCode", () => {
  it("verifies the code and returns the session", async () => {
    const { client, verifyOtp } = fakeClient();
    const session = await verifyEmailCode(client, "Ada@example.com", "123 456");
    expect(session).toEqual({ access_token: "jwt" });
    expect(verifyOtp).toHaveBeenCalledWith({
      email: "ada@example.com",
      token: "123456",
      type: "email",
    });
  });

  it("rejects a malformed code locally and a wrong code from the server", async () => {
    const { client, verifyOtp } = fakeClient({ verifyError: "Token has expired or is invalid" });
    await expect(verifyEmailCode(client, "a@b.io", "12")).rejects.toThrow(/6-digit/);
    expect(verifyOtp).not.toHaveBeenCalled();
    await expect(verifyEmailCode(client, "a@b.io", "123456")).rejects.toThrow(/expired or is invalid/);
  });

  it("treats a response without a session as a failure", async () => {
    const { client } = fakeClient({ session: false });
    await expect(verifyEmailCode(client, "a@b.io", "123456")).rejects.toThrow(/could not sign in/i);
  });
});

describe("sign-in screen wiring", () => {
  const screen = fs.readFileSync(path.join(ROOT, "app/index.tsx"), "utf8");

  it("shows the email form only when email sign-in is enabled and configured", () => {
    expect(screen).toMatch(/emailAvailable\s*=\s*emailEnabled && \(socialConfigured \|\| demo\)/);
    expect(screen).toMatch(/\{emailAvailable \? \(\s*<EmailCodeSignIn/);
  });

  it("an email session goes through the same identity-backed device session", () => {
    expect(screen).toMatch(/continueWith\("email"/);
  });

  it("counts email as a provider so the 'being set up' notice hides", () => {
    expect(screen).toMatch(/anyProvider\s*=\s*appleAvailable \|\| googleAvailable \|\| emailAvailable/);
  });
});
