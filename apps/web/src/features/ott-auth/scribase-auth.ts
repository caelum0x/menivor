/**
 * Viewer sign-in on Scribase Auth (MV6, dogfood). The browser talks to the
 * Menivor viewers project directly with its publishable anon key: an email
 * code is sent, the viewer types it, and Scribase Auth returns an access
 * token that our API exchanges once for a channel session.
 */

export interface ScribaseAuthConfig {
  readonly url: string;
  readonly anonKey: string;
}

export function scribaseAuthConfig(): ScribaseAuthConfig | null {
  const url = (process.env.NEXT_PUBLIC_SCRIBASE_VIEWERS_URL ?? "").replace(/\/+$/, "");
  const anonKey = process.env.NEXT_PUBLIC_SCRIBASE_VIEWERS_ANON_KEY ?? "";
  return url && anonKey ? { url, anonKey } : null;
}

export class SignInError extends Error {}

async function call(config: ScribaseAuthConfig, path: string, body: unknown): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(`${config.url}/auth/v1/${path}`, {
      method: "POST",
      headers: { apikey: config.anonKey, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new SignInError("We could not reach sign-in. Check your connection and try again.");
  }
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    if (response.status === 429) throw new SignInError("Too many tries. Wait a minute and try again.");
    throw new SignInError(path === "verify" ? "That code did not work. Ask for a new one." : "We could not send a code to that email.");
  }
  return data;
}

export async function requestCode(email: string, config = scribaseAuthConfig()): Promise<void> {
  if (!config) throw new SignInError("Sign-in is not available right now.");
  await call(config, "otp", { email: email.trim().toLowerCase(), create_user: true });
}

export async function verifyCode(email: string, code: string, config = scribaseAuthConfig()): Promise<string> {
  if (!config) throw new SignInError("Sign-in is not available right now.");
  const data = await call(config, "verify", { type: "email", email: email.trim().toLowerCase(), token: code.trim() });
  const token = typeof data.access_token === "string" ? data.access_token : "";
  if (!token) throw new SignInError("That code did not work. Ask for a new one.");
  return token;
}
