"use client";

import * as React from "react";
import { Copy, KeyRound, PlugZap, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { getConnector, listTokens, mintToken, revokeToken, type ConnectorInfo, type McpToken } from "./api";

const CARD = "rounded-2xl border border-white/10 bg-white/[0.03] p-5 shadow-[inset_0_1px_0_hsl(0_0%_100%/0.05)]";

function day(value: string | null): string {
  return value ? value.slice(0, 10) : "never";
}

function CopyField({ label, value, multiline = false }: { label: string; value: string; multiline?: boolean }) {
  const [copied, setCopied] = React.useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <Button variant="ghost" size="sm" onClick={copy} aria-label={`Copy ${label}`}>
          <Copy className="size-4" aria-hidden /> {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre className={`overflow-x-auto rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs ${multiline ? "" : "whitespace-nowrap"}`}>
        {value}
      </pre>
    </div>
  );
}

function CreateToken({ onMinted }: { onMinted: (t: McpToken) => void }) {
  const requestOptions = useRequestOptions();
  const [name, setName] = React.useState("Claude");
  const [read, setRead] = React.useState(true);
  const [write, setWrite] = React.useState(true);
  const [workspace, setWorkspace] = React.useState("");
  const [ttl, setTtl] = React.useState("90");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const scopes = [read ? "read" : "", write ? "write" : ""].filter(Boolean);
      onMinted(await mintToken({ name, scopes, workspace_id: workspace.trim() || undefined, ttl_days: Number(ttl) },
        await requestOptions()));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Create token">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="mcp-name">Name</Label>
          <Input id="mcp-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="mcp-ws">Workspace id (optional)</Label>
          <Input id="mcp-ws" value={workspace} maxLength={32} onChange={(e) => setWorkspace(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="mcp-ttl">Expires after</Label>
          <Select id="mcp-ttl" value={ttl} onChange={(e) => setTtl(e.target.value)}>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
            <option value="365">365 days</option>
          </Select>
        </div>
      </div>
      <div className="flex gap-4 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} /> Read</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={write} onChange={(e) => setWrite(e.target.checked)} /> Write (requests only, approvals stay with you)</label>
      </div>
      <ErrorText message={error} />
      <Button type="submit" disabled={busy || !name.trim() || (!read && !write)}>{busy ? "Creating..." : "Create token"}</Button>
    </form>
  );
}

/** Settings > MCP connector: endpoint, client setup, tools, and connector tokens. */
export function McpConnector() {
  const requestOptions = useRequestOptions();
  const [info, setInfo] = React.useState<ConnectorInfo | null>(null);
  const [tokens, setTokens] = React.useState<McpToken[]>([]);
  const [fresh, setFresh] = React.useState<McpToken | null>(null);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const o = await requestOptions();
      const [i, t] = await Promise.all([getConnector(o), listTokens(o)]);
      setInfo(i);
      setTokens(t);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [requestOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function revoke(id: string) {
    setError("");
    try {
      await revokeToken(id, await requestOptions());
      if (fresh?.id === id) setFresh(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-8" data-testid="mcp-page">
      <div className="space-y-2">
        <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
          <PlugZap className="size-7 text-primary" aria-hidden /> MCP connector
        </h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Connect Claude or another AI agent to Menivor: brand memory, Ad Clone, generation requests, approvals and ad analytics.
        </p>
        <ul className="space-y-1 text-sm text-muted-foreground" aria-label="Rules">
          {(info?.rules ?? []).map((r) => (
            <li key={r} className="flex items-start gap-2"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden /> {r}</li>
          ))}
        </ul>
      </div>
      <ErrorText message={error} />

      {info ? (
        <section className={`${CARD} space-y-4`} aria-label="Endpoint">
          <CopyField label="Endpoint" value={info.url} />
          <CopyField label="Claude Code" value={info.claude_code} />
          <CopyField label="JSON config" value={JSON.stringify(info.json_config, null, 2)} multiline />
        </section>
      ) : null}

      <section className={`${CARD} space-y-4`} aria-label="Tokens">
        <h2 className="flex items-center gap-2 text-lg font-semibold"><KeyRound className="size-5 text-primary" aria-hidden /> Tokens</h2>
        {fresh?.token ? (
          <div className="space-y-2 rounded-xl border border-primary/40 bg-primary/[0.08] p-3" role="status" data-testid="fresh-token">
            <p className="text-sm font-medium">Copy this token now. You will not see it again.</p>
            <CopyField label="Token" value={fresh.token} />
            <Button variant="ghost" size="sm" onClick={() => setFresh(null)}>Done</Button>
          </div>
        ) : null}
        <CreateToken onMinted={(t) => { setFresh(t); void load(); }} />
        <ul className="divide-y divide-white/10" aria-label="Token list">
          {tokens.length === 0 ? <li className="py-2 text-sm text-muted-foreground">No tokens yet.</li> : null}
          {tokens.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <span className="space-x-2">
                <span className="font-medium">{t.name}</span>
                <code className="text-xs text-muted-foreground">{t.prefix}...</code>
                {t.scopes.map((s) => <Badge key={s} variant="outline">{s}</Badge>)}
                {t.revoked ? <Badge variant="destructive">Revoked</Badge> : null}
              </span>
              <span className="flex items-center gap-3 text-xs text-muted-foreground">
                <span>Expires {day(t.expires_at)}</span>
                <span>Last used {day(t.last_used_at)}</span>
                {!t.revoked ? <Button variant="outline" size="sm" onClick={() => revoke(t.id)}>Revoke</Button> : null}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {info ? (
        <section className={`${CARD} space-y-3`} aria-label="Tools">
          <h2 className="text-lg font-semibold">Tools</h2>
          <ul className="grid gap-2 sm:grid-cols-2">
            {info.tools.map((t) => (
              <li key={t.name} className="rounded-xl border border-white/10 px-3 py-2">
                <p className="flex items-center gap-2 text-sm font-medium">
                  <code>{t.name}</code>
                  {t.annotations?.readOnlyHint ? <Badge variant="secondary">read only</Badge> : null}
                </p>
                <p className="text-xs text-muted-foreground">{t.description}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
