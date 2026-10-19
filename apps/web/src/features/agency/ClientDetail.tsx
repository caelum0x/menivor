"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Coins, Plus, RefreshCw, UserPlus } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { formatUsdMicros } from "./api";
import { getCredits, grantCredits, inviteMember, listMembers, type Member } from "./clients";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** A client (workspace) detail: shared credit pool, roster, invite + grant. */
export function ClientDetail({ clientId }: { clientId: string }) {
  const { getToken } = useAuth();
  const [members, setMembers] = React.useState<Member[]>([]);
  const [balance, setBalance] = React.useState<number | null>(null);
  const [error, setError] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState("member");
  const [grant, setGrant] = React.useState(10);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const [ms, c] = await Promise.all([listMembers(clientId, { token }), getCredits(clientId, { token })]);
      setMembers(ms);
      setBalance(c.balance);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to load client."));
    }
  }, [clientId, getToken]);

  React.useEffect(() => { void load(); }, [load]);

  const onInvite = React.useCallback(async () => {
    if (!email.trim()) return;
    setBusy(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      await inviteMember(clientId, email.trim(), role, { token });
      setEmail("");
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "Invite failed."));
    } finally {
      setBusy(false);
    }
  }, [email, role, clientId, getToken, load]);

  const onGrant = React.useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      // Grant is in credits; the pool is integer micros (1 credit = 10_000 micros).
      const { balance: b } = await grantCredits(clientId, Math.round(grant) * 10_000, { token });
      setBalance(b);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Grant failed."));
    } finally {
      setBusy(false);
    }
  }, [grant, clientId, getToken]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground"><Coins className="h-4 w-4" /> Shared credit pool</div>
            <div className="text-2xl font-semibold">{balance === null ? "…" : formatUsdMicros(balance)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-end gap-3 py-4">
            <div className="flex-1">
              <label className="mb-1 block text-sm font-medium">Grant credits</label>
              <Input type="number" value={grant} min={1} onChange={(e) => setGrant(Number(e.target.value) || 0)} />
            </div>
            <Button onClick={onGrant} disabled={busy}><Plus className="mr-1 h-4 w-4" /> Grant</Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 py-4">
          <div className="flex-1">
            <label className="mb-1 block text-sm font-medium">Invite by email</label>
            <Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teammate@acme.co" />
          </div>
          <select className="rounded-md border bg-transparent px-3 py-2 text-sm" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="member">member</option>
            <option value="admin">admin</option>
          </select>
          <Button onClick={onInvite} disabled={busy || !email.trim()}><UserPlus className="mr-1 h-4 w-4" /> Invite</Button>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Members</h2>
        <Button size="sm" variant="ghost" onClick={() => void load()} aria-label="Refresh"><RefreshCw className="h-4 w-4" /></Button>
      </div>
      <div className="space-y-2">
        {members.map((m) => (
          <Card key={m.user_id}>
            <CardContent className="flex items-center justify-between py-3">
              <div className="text-sm">{m.email ?? m.user_id}</div>
              <Badge variant={m.role === "owner" ? "secondary" : "outline"}>{m.role}</Badge>
            </CardContent>
          </Card>
        ))}
        {members.length === 0 ? <Card><CardContent className="py-6 text-sm text-muted-foreground">No members yet.</CardContent></Card> : null}
      </div>

      {error ? <div className="text-sm text-red-600">{error}</div> : null}
    </div>
  );
}
