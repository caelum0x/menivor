/**
 * MN9: which auth project the app signs in against, and cleanup of a previous
 * project's stored session. Run: npx vitest run src/shared/auth/__tests__/supabase-config.test.ts
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("@react-native-async-storage/async-storage", () => ({
  default: { getAllKeys: async () => [], multiRemove: async () => undefined },
}));
vi.mock("@supabase/supabase-js", () => ({ createClient: () => ({}) }));
vi.mock("expo-constants", () => ({ default: { expoConfig: { extra: {} } } }));

import { resolveAuthProject, sessionStorageKey, staleSessionKeys } from "../supabase";

const SCRIBASE = { url: "https://menivor.scribase.example/", anonKey: "sb_publishable_scribase" };
const OLD_ENV = {
  EXPO_PUBLIC_SUPABASE_URL: "https://psqkkdjzgptfcqpxuxki.supabase.co",
  EXPO_PUBLIC_SUPABASE_ANON_KEY: "sb_publishable_old",
};

describe("resolveAuthProject", () => {
  it("prefers the Scribase project in app.json extra.auth over the env fallback", () => {
    expect(resolveAuthProject({ auth: SCRIBASE }, OLD_ENV)).toEqual({
      url: "https://menivor.scribase.example",
      anonKey: "sb_publishable_scribase",
      source: "app.json",
    });
  });

  it("keeps the env project while extra.auth is empty (existing builds unchanged)", () => {
    expect(resolveAuthProject({ auth: { provider: "scribase", url: "", anonKey: "" } }, OLD_ENV)).toEqual({
      url: OLD_ENV.EXPO_PUBLIC_SUPABASE_URL,
      anonKey: OLD_ENV.EXPO_PUBLIC_SUPABASE_ANON_KEY,
      source: "env",
    });
  });

  it("needs both a URL and a key from one source", () => {
    expect(resolveAuthProject({ auth: { url: SCRIBASE.url } }, {}).source).toBe("none");
    expect(resolveAuthProject(undefined, { EXPO_PUBLIC_SUPABASE_URL: OLD_ENV.EXPO_PUBLIC_SUPABASE_URL }).source).toBe("none");
  });
});

describe("stored sessions", () => {
  it("pins the key supabase-js derives from the project host", () => {
    expect(sessionStorageKey("https://psqkkdjzgptfcqpxuxki.supabase.co")).toBe("sb-psqkkdjzgptfcqpxuxki-auth-token");
    expect(sessionStorageKey("https://menivor.scribase.example")).toBe("sb-menivor-auth-token");
  });

  it("finds the old project's session and verifier, and nothing else", () => {
    const current = sessionStorageKey("https://menivor.scribase.example");
    const keys = [
      current,
      `${current}-code-verifier`,
      "sb-psqkkdjzgptfcqpxuxki-auth-token",
      "sb-psqkkdjzgptfcqpxuxki-auth-token-code-verifier",
      "menivor.drafts.v1",
      "revenuecat.appUserId",
    ];
    expect(staleSessionKeys(keys, current)).toEqual([
      "sb-psqkkdjzgptfcqpxuxki-auth-token",
      "sb-psqkkdjzgptfcqpxuxki-auth-token-code-verifier",
    ]);
  });
});
