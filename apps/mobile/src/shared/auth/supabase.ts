/**
 * Lazily-created auth client for native social sign-in (Scribase Auth, which
 * speaks the Supabase Auth API, so supabase-js is the client).
 *
 * Where the project comes from, first match wins:
 *   1. app.json `expo.extra.auth` { url, anonKey } — the Menivor project on
 *      Scribase (MN9). One config edit switches every build.
 *   2. EXPO_PUBLIC_SUPABASE_URL + EXPO_PUBLIC_SUPABASE_ANON_KEY (EAS
 *      environment variables / .env.local, written by
 *      ~/products/deploy-scripts/scribase-move-apps.sh). Nothing is hardcoded.
 * Both values are safe to ship in a client build: the anon key is a public,
 * RLS-gated key. Runbook: docs/runbooks/mobile-auth-scribase.md.
 *
 * The session is persisted with AsyncStorage so it survives app restarts. When
 * the project changes, the old project's stored session is removed once, so a
 * token for a project the API no longer trusts is never sent.
 *
 * Everything here fails closed: without a URL and key the client is never
 * created and `getSupabaseClient()` returns null, so builds without auth
 * configured keep working exactly as before (this layer is additive/optional).
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import Constants from "expo-constants";

export interface AuthProjectConfig {
  url: string;
  anonKey: string;
  source: "app.json" | "env" | "none";
}

function clean(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** Resolve the auth project from app.json extra, then the public env vars. */
export function resolveAuthProject(
  extra: unknown = Constants.expoConfig?.extra,
  env: Record<string, string | undefined> = {
    EXPO_PUBLIC_SUPABASE_URL: process.env.EXPO_PUBLIC_SUPABASE_URL,
    EXPO_PUBLIC_SUPABASE_ANON_KEY: process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY,
  },
): AuthProjectConfig {
  const auth =
    extra && typeof extra === "object" ? (extra as { auth?: unknown }).auth : undefined;
  const fromExtra =
    auth && typeof auth === "object" ? (auth as { url?: unknown; anonKey?: unknown }) : {};
  const extraUrl = clean(fromExtra.url).replace(/\/+$/, "");
  const extraKey = clean(fromExtra.anonKey);
  if (extraUrl && extraKey) return { url: extraUrl, anonKey: extraKey, source: "app.json" };

  const envUrl = clean(env.EXPO_PUBLIC_SUPABASE_URL).replace(/\/+$/, "");
  const envKey = clean(env.EXPO_PUBLIC_SUPABASE_ANON_KEY);
  if (envUrl && envKey) return { url: envUrl, anonKey: envKey, source: "env" };

  return { url: "", anonKey: "", source: "none" };
}

/**
 * The AsyncStorage key supabase-js uses for a project URL
 * (`sb-<first host label>-auth-token`), pinned so it never drifts with the SDK.
 */
export function sessionStorageKey(url: string): string {
  let host = "";
  try {
    host = new URL(url).hostname;
  } catch {
    host = url;
  }
  return `sb-${host.split(".")[0]}-auth-token`;
}

const SESSION_KEY_RE = /^sb-[^/]+-auth-token(-code-verifier)?$/;

/** Stored sessions that belong to another project than `currentKey`. */
export function staleSessionKeys(keys: readonly string[], currentKey: string): string[] {
  return keys.filter(
    (key) =>
      SESSION_KEY_RE.test(key) && key !== currentKey && key !== `${currentKey}-code-verifier`,
  );
}

const PROJECT = resolveAuthProject();
const STORAGE_KEY = PROJECT.url ? sessionStorageKey(PROJECT.url) : "";

// Menivor has its own Scribase project (apps/mobile/scribase/), so its tables
// are in the default `public` schema.
const createMenivorClient = () =>
  createClient(PROJECT.url, PROJECT.anonKey, {
    auth: {
      storage: AsyncStorage,
      storageKey: STORAGE_KEY,
      autoRefreshToken: true,
      persistSession: true,
      // React Native has no URL-based OAuth redirect to parse.
      detectSessionInUrl: false,
    },
  });

let client: SupabaseClient | null = null;

async function pruneStaleSessions(): Promise<void> {
  try {
    const stale = staleSessionKeys(await AsyncStorage.getAllKeys(), STORAGE_KEY);
    if (stale.length > 0) await AsyncStorage.multiRemove(stale);
  } catch {
    // Best effort: a leftover key is ignored by the client anyway.
  }
}

/** True only when an auth project URL and key are configured for this build. */
export function isSupabaseConfigured(): boolean {
  return PROJECT.url.length > 0 && PROJECT.anonKey.length > 0;
}

/** Which config source this build's auth project came from (for diagnostics). */
export function authProjectSource(): AuthProjectConfig["source"] {
  return PROJECT.source;
}

/**
 * Returns the singleton client, or null when auth is not configured for this
 * build. Callers must treat null as "sign-in unavailable".
 */
export function getSupabaseClient(): SupabaseClient | null {
  if (!isSupabaseConfigured()) return null;
  if (client) return client;

  void pruneStaleSessions();
  client = createMenivorClient();
  return client;
}
