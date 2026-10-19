"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import { Building2, Plus, RefreshCw } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { createClient, listClients, type Client } from "./clients";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Manage client accounts (each is a workspace with a shared credit pool). */
export function AgencyClients() {
  const { getToken } = useAuth();
  const [clients, setClients] = React.useState<Client[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      setClients(await listClients({ token }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to load clients."));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const onCreate = React.useCallback(async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      await createClient(name.trim(), { token });
      setName("");
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to create client."));
    } finally {
      setBusy(false);
    }
  }, [name, getToken, load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Clients</h2>
        <Button size="sm" variant="ghost" onClick={() => void load()} aria-label="Refresh">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      <Card>
        <CardContent className="flex items-end gap-3 py-4">
          <div className="flex-1">
            <label className="mb-1 block text-sm font-medium">New client</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Co." />
          </div>
          <Button onClick={onCreate} disabled={busy || !name.trim()}>
            <Plus className="mr-1 h-4 w-4" /> Add client
          </Button>
        </CardContent>
      </Card>

      {error ? <Card><CardContent className="py-4 text-sm text-red-600">{error}</CardContent></Card> : null}

      <div className="space-y-2">
        {loading ? (
          <Card><CardContent className="py-6 text-sm text-muted-foreground">Loading…</CardContent></Card>
        ) : clients.length === 0 ? (
          <Card><CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground"><Building2 className="h-4 w-4" /> No clients yet — add one above.</CardContent></Card>
        ) : (
          clients.map((c) => (
            <Link key={c.id} href={`/agency/clients/${c.id}`} className="block">
            <Card className="transition-colors hover:border-primary">
              <CardContent className="flex items-center justify-between py-3">
                <div>
                  <div className="font-medium">{c.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {c.created_at ? new Date(c.created_at).toLocaleDateString() : "—"}
                  </div>
                </div>
                <Badge variant={c.role === "owner" ? "secondary" : "outline"}>{c.role}</Badge>
              </CardContent>
            </Card>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
