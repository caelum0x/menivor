/**
 * Removes the caller's Apple/Google sign-in identity from Menivor's Scribase
 * project (public.delete_own_account(), scribase/migrations/0002). Called after
 * the Menivor API has erased the account (POST /me/erase), so nothing personal
 * stays behind in the auth project either (App Store guideline 5.1.1(v)).
 *
 * Best effort and never throws: the account erasure already succeeded, and an
 * install without a Scribase session (device/API-key account, auth not
 * configured) has no identity to delete.
 */

import type { SupabaseClient } from "@supabase/supabase-js";

export type IdentityDeletion = "deleted" | "no_session" | "not_configured" | "failed";

export async function deleteSignInIdentity(
  client: SupabaseClient | null,
): Promise<IdentityDeletion> {
  if (!client) return "not_configured";
  try {
    const { data } = await client.auth.getSession();
    if (!data.session) return "no_session";
    const { data: outcome, error } = await client.rpc("delete_own_account");
    if (error || outcome !== "account_deleted") return "failed";
    await client.auth.signOut({ scope: "local" }).catch(() => undefined);
    return "deleted";
  } catch {
    return "failed";
  }
}
