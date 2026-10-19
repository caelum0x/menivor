/**
 * OAuth connect flow for the Connections screen.
 *
 * The backend mints an opaque `authorize_url` (which already embeds a single-use
 * CSRF `state`); we open it in an in-app auth session and wait for the provider
 * to redirect back to our app deep link with `code` + the echoed `state`, then
 * hand those to the token-free callback to finish the handshake.
 *
 * SECURITY: nothing sensitive lives here. No access/refresh token is ever
 * requested, parsed, or returned — the callback yields only the token-free
 * connection list. The only value we forward is the opaque `code` + `state`.
 */

import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import { completeConnect, startConnect } from "@/lib/api";
import type { Connection, SocialProvider } from "@/lib/types";

/** Thrown when the user dismisses/cancels the in-app auth browser. */
export class ConnectCancelledError extends Error {
  constructor(message = "Connection cancelled.") {
    super(message);
    this.name = "ConnectCancelledError";
  }
}

/** Narrow a `string | string[] | undefined` query param to its first string. */
function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return typeof value[0] === "string" ? value[0] : "";
  return typeof value === "string" ? value : "";
}

/**
 * Runs the full connect handshake for `provider` and resolves with the
 * refreshed, token-free connection list on success.
 *
 * Throws {@link ConnectCancelledError} if the user backs out of the browser,
 * and a plain Error (with a user-facing message) if the provider returns an
 * error or no authorization code.
 */
export async function connectProvider(
  provider: SocialProvider | string,
  token: string | undefined,
  scopes?: string,
): Promise<Connection[]> {
  const info = await startConnect(provider, { token, scopes });

  // The deep link the provider should redirect back to once the user approves.
  const returnUrl = Linking.createURL("connections");

  const result = await WebBrowser.openAuthSessionAsync(
    info.authorize_url,
    returnUrl,
  );

  if (result.type !== "success" || !result.url) {
    throw new ConnectCancelledError();
  }

  const { queryParams } = Linking.parse(result.url);
  const providerError = firstParam(queryParams?.error);
  if (providerError) {
    throw new Error(`The provider reported an error: ${providerError}.`);
  }

  const code = firstParam(queryParams?.code);
  // Prefer the state the provider echoed back; fall back to the minted one.
  const state = firstParam(queryParams?.state) || info.state;
  if (!code) {
    throw new Error("The provider did not return an authorization code.");
  }

  return completeConnect(provider, code, state, { token });
}
