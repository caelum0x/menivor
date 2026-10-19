"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Loader2 } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import {
  createKey,
  listKeys,
  quoteKey,
  revokeKey,
  type CreateKeyBody,
  type ProvisioningKey,
  type Quote,
} from "./api";
import { KeyCard } from "./KeyCard";
import { MintKeyForm } from "./MintKeyForm";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/**
 * Gateway resell console: the reseller mints provisioning keys (daily cap +
 * markup), lists them, revokes them, and previews customer prices — all wired
 * to the live gateway domain through the shared authenticated transport.
 */
export function GatewayConsole() {
  const { getToken } = useAuth();
  const [keys, setKeys] = React.useState<ProvisioningKey[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const messageOf = (err: unknown, fallback: string): string =>
    friendlyErrorMessage(err, fallback);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const token = (await getToken()) ?? undefined;
      const res = await listKeys({ token });
      setKeys(res.keys);
      setError("");
    } catch (err) {
      setError(messageOf(err, "Failed to load keys."));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const onMint = React.useCallback(
    async (body: CreateKeyBody): Promise<ProvisioningKey> => {
      const token = (await getToken()) ?? undefined;
      const key = await createKey(body, {
        token,
        idempotencyKey: crypto.randomUUID(),
      });
      await load();
      return key;
    },
    [getToken, load],
  );

  const onRevoke = React.useCallback(
    async (keyId: string): Promise<void> => {
      const token = (await getToken()) ?? undefined;
      await revokeKey(keyId, { token });
      await load();
    },
    [getToken, load],
  );

  const onQuote = React.useCallback(
    async (keyId: string, baseCostMicros: number): Promise<Quote> => {
      const token = (await getToken()) ?? undefined;
      return quoteKey(keyId, baseCostMicros, { token });
    },
    [getToken],
  );

  return (
    <div className="space-y-6">
      <MintKeyForm onMint={onMint} />

      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading keys…
        </p>
      ) : keys.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No provisioning keys yet — mint one above to start reselling.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {keys.map((k) => (
            <KeyCard
              key={k.id}
              keyRow={k}
              onRevoke={onRevoke}
              onQuote={onQuote}
            />
          ))}
        </div>
      )}
    </div>
  );
}
