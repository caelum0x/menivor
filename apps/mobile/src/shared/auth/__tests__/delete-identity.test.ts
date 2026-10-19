/**
 * Sign-in identity deletion after the Menivor account is erased.
 * Run: npx vitest run src/shared/auth/__tests__/delete-identity.test.ts
 */
import { describe, expect, it, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";

import { deleteSignInIdentity } from "../delete-identity";

function fakeClient(opts: { session: boolean; rpc?: { data: unknown; error: unknown }; throws?: boolean }) {
  const signOut = vi.fn(async () => ({ error: null }));
  const rpc = vi.fn(async () => {
    if (opts.throws) throw new Error("offline");
    return opts.rpc ?? { data: "account_deleted", error: null };
  });
  const client = {
    auth: {
      getSession: async () => ({ data: { session: opts.session ? { access_token: "t" } : null } }),
      signOut,
    },
    rpc,
  } as unknown as SupabaseClient;
  return { client, rpc, signOut };
}

describe("deleteSignInIdentity", () => {
  it("is a no-op without a configured client", async () => {
    expect(await deleteSignInIdentity(null)).toBe("not_configured");
  });

  it("does nothing without a session", async () => {
    const { client, rpc } = fakeClient({ session: false });
    expect(await deleteSignInIdentity(client)).toBe("no_session");
    expect(rpc).not.toHaveBeenCalled();
  });

  it("calls delete_own_account and drops the local session", async () => {
    const { client, rpc, signOut } = fakeClient({ session: true });
    expect(await deleteSignInIdentity(client)).toBe("deleted");
    expect(rpc).toHaveBeenCalledWith("delete_own_account");
    expect(signOut).toHaveBeenCalledWith({ scope: "local" });
  });

  it("reports a refused or unexpected answer without throwing", async () => {
    expect(await deleteSignInIdentity(fakeClient({ session: true, rpc: { data: null, error: { message: "no" } } }).client)).toBe("failed");
    expect(await deleteSignInIdentity(fakeClient({ session: true, rpc: { data: "x", error: null } }).client)).toBe("failed");
    expect(await deleteSignInIdentity(fakeClient({ session: true, throws: true }).client)).toBe("failed");
  });
});
