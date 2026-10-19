/**
 * Shared native-auth state for the user's ReelForge API key.
 *
 * The key is sent as the `x-api-key` header on every request (see lib/api.ts,
 * passed as `options.token`). It is persisted with expo-secure-store so it
 * survives app restarts, and exposed to the tree via a small React context.
 *
 * No secrets are hardcoded — the key is entered by the user on the sign-in
 * screen (app/index.tsx).
 */

import { createContext, useContext } from "react";

import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";

const API_KEY_STORE = "reelforge.apiKey";
const INSTALL_ID_STORE = "reelforge.installId";

/** Reads the stored API key, or null if the user hasn't signed in. */
export async function loadApiKey(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(API_KEY_STORE);
  } catch {
    return null;
  }
}

/** Persists the API key for future launches. */
export async function saveApiKey(key: string): Promise<void> {
  await SecureStore.setItemAsync(API_KEY_STORE, key);
}

/** Clears the stored API key (sign out). */
export async function clearApiKey(): Promise<void> {
  await SecureStore.deleteItemAsync(API_KEY_STORE);
}

function createInstallId(): string {
  return `rf-install-${Crypto.randomUUID()}`;
}

/** Returns a stable, high-entropy installation id stored in the OS keychain. */
export async function getOrCreateInstallId(): Promise<string> {
  const existing = await SecureStore.getItemAsync(INSTALL_ID_STORE);
  if (existing) return existing;
  const created = createInstallId();
  await SecureStore.setItemAsync(INSTALL_ID_STORE, created);
  return created;
}

export interface SessionValue {
  /** The current API key, or null when signed out. */
  apiKey: string | null;
  /** True until the persisted key has been loaded on startup. */
  loading: boolean;
  /** Persists a new key and updates the context. */
  signIn: (key: string) => Promise<void>;
  /** Clears the key and updates the context. */
  signOut: () => Promise<void>;
}

export const SessionContext = createContext<SessionValue | null>(null);

/** Access the current session. Must be used under <SessionProvider>. */
export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return ctx;
}
