/**
 * Email sign-in with a one-time code on Scribase Auth (Supabase Auth API).
 *
 * This is the sign-in that works on every device (Sign in with Apple is
 * iOS-only and Google waits for Menivor's own OAuth client). The user types an
 * email, gets a 6-digit code, types it back; the resulting session is traded
 * for a Menivor account exactly like an Apple/Google session.
 *
 * Off until the build turns it on (app.json `expo.extra.auth.email: true` or
 * `EXPO_PUBLIC_EMAIL_SIGNIN=1`), because it needs the Scribase project's email
 * provider and SMTP sender to be live first (apps/mobile/scribase/project.json).
 */

import type { Session, SupabaseClient } from "@supabase/supabase-js";

/** Scribase/GoTrue default OTP length (mailer_otp_length unset). */
export const EMAIL_CODE_LENGTH = 6;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/** True when this build offers email sign-in. */
export function isEmailSignInEnabled(
  extra: unknown,
  env: { EXPO_PUBLIC_EMAIL_SIGNIN?: string },
): boolean {
  const auth =
    extra && typeof extra === "object" ? (extra as { auth?: unknown }).auth : undefined;
  if (auth && typeof auth === "object" && (auth as { email?: unknown }).email === true) {
    return true;
  }
  return env.EXPO_PUBLIC_EMAIL_SIGNIN?.trim() === "1";
}

/** Lower-cased, trimmed email, or null when it is not a plausible address. */
export function normalizeEmail(raw: string): string | null {
  const email = raw.trim().toLowerCase();
  return EMAIL_RE.test(email) ? email : null;
}

/** The code with spaces removed, or null unless it is exactly 6 digits. */
export function normalizeEmailCode(raw: string): string | null {
  const code = raw.replace(/\s+/g, "");
  return new RegExp(`^\\d{${EMAIL_CODE_LENGTH}}$`).test(code) ? code : null;
}

function requireClient(client: SupabaseClient | null): SupabaseClient {
  if (!client) throw new Error("Email sign-in is not available in this build yet.");
  return client;
}

/** Send a sign-in code. The account is created on first use (signup-first). */
export async function requestEmailCode(
  client: SupabaseClient | null,
  rawEmail: string,
): Promise<void> {
  const email = normalizeEmail(rawEmail);
  if (!email) throw new Error("Enter a valid email address.");
  const { error } = await requireClient(client).auth.signInWithOtp({
    email,
    options: { shouldCreateUser: true },
  });
  if (error) throw new Error(error.message || "Could not send the code. Try again.");
}

/** Check the code and return the Scribase session. */
export async function verifyEmailCode(
  client: SupabaseClient | null,
  rawEmail: string,
  rawCode: string,
): Promise<Session> {
  const email = normalizeEmail(rawEmail);
  if (!email) throw new Error("Enter a valid email address.");
  const code = normalizeEmailCode(rawCode);
  if (!code) throw new Error(`Enter the ${EMAIL_CODE_LENGTH}-digit code from the email.`);
  const { data, error } = await requireClient(client).auth.verifyOtp({
    email,
    token: code,
    type: "email",
  });
  if (error) throw new Error(error.message || "That code did not work. Try again.");
  if (!data.session) throw new Error("Could not sign in with that code. Request a new one.");
  return data.session;
}
