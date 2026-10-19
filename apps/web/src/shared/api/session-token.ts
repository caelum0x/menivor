/**
 * The signed-in session token for API calls that do not pass one explicitly.
 *
 * `ApiSessionBridge` (mounted once in the root layout) registers Clerk's
 * token getter here, so every request made by the web app authenticates as
 * the signed-in account without each feature threading a token through.
 */

type TokenGetter = () => Promise<string | null | undefined>;

let getter: TokenGetter | null = null;

export function setSessionTokenGetter(next: TokenGetter | null): void {
  getter = next;
}

/** The current session token, or "" when signed out / unavailable. */
export async function getSessionToken(): Promise<string> {
  if (!getter) return "";
  try {
    return (await getter()) ?? "";
  } catch {
    return "";
  }
}
