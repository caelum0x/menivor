"use client";

import * as React from "react";
import { Bot, Building2, Copy, Power, Server } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type {
  WalletDestinationBalance,
  WalletDestinationProfile,
  WalletDestinationProfileRequest,
  WalletSource,
} from "./api";
import { formatUsdMicros } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface WalletDestinationsProps {
  sources: WalletSource[];
  destinations: WalletDestinationProfile[];
  loading: boolean;
  createDestination: (
    request: WalletDestinationProfileRequest,
  ) => Promise<WalletDestinationProfile>;
  setDestinationActive: (
    destinationId: string,
    active: boolean,
  ) => Promise<WalletDestinationProfile>;
  loadBalance: (destinationId: string) => Promise<WalletDestinationBalance>;
}

const kindIcon = {
  workspace: Building2,
  agent: Bot,
  service: Server,
} as const;

function messageOf(error: unknown): string {
  return friendlyErrorMessage(error, "Could not update receive identities.");
}

/** Management journey for real Mint-backed non-person receive principals. */
export function WalletDestinations({
  sources,
  destinations,
  loading,
  createDestination,
  setDestinationActive,
  loadBalance,
}: WalletDestinationsProps) {
  const workspaceSources = sources.filter((source) => source.kind === "workspace");
  const [kind, setKind] = React.useState<"workspace" | "agent" | "service">("agent");
  const [scope, setScope] = React.useState<"personal" | "workspace">("personal");
  const [workspaceSourceId, setWorkspaceSourceId] = React.useState("");
  const [slug, setSlug] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const [balances, setBalances] = React.useState<Record<string, WalletDestinationBalance>>({});

  React.useEffect(() => {
    let active = true;
    void Promise.all(
      destinations.map(async (destination) => {
        try {
          return await loadBalance(destination.destination_id);
        } catch {
          return null;
        }
      }),
    ).then((results) => {
      if (!active) return;
      const next: Record<string, WalletDestinationBalance> = {};
      for (const result of results) {
        if (result) next[result.destination.destination_id] = result;
      }
      setBalances(next);
    });
    return () => { active = false; };
  }, [destinations, loadBalance]);

  React.useEffect(() => {
    if (kind === "workspace") setScope("workspace");
  }, [kind]);

  const requiresWorkspace = kind === "workspace" || scope === "workspace";
  const valid = /^[a-z0-9](?:[a-z0-9-]{1,46}[a-z0-9])?$/.test(slug)
    && displayName.trim().length > 0
    && (!requiresWorkspace || workspaceSourceId.length > 0);

  const onCreate = React.useCallback(async () => {
    if (!valid) return;
    setSubmitting(true);
    setError("");
    try {
      await createDestination({
        kind,
        slug,
        display_name: displayName.trim(),
        ...(requiresWorkspace
          ? { workspace_source_account_id: workspaceSourceId }
          : {}),
      });
      setSlug("");
      setDisplayName("");
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setSubmitting(false);
    }
  }, [createDestination, displayName, kind, requiresWorkspace, slug, valid, workspaceSourceId]);

  return (
    <section className="mt-8 border border-zinc-200 bg-white text-zinc-950">
      <div className="grid border-b border-zinc-200 md:grid-cols-[1fr_18rem]">
        <div className="p-5 md:border-r md:border-zinc-200">
          <h2 className="text-xl font-semibold tracking-tight">Receive identities</h2>
          <p className="mt-1 max-w-xl text-sm text-zinc-600">
            Create a public workspace, agent, or service destination. Every identity
            receives into its own Mint account and can be disabled without deleting its history.
          </p>
        </div>
        <div className="border-t border-zinc-200 p-5 md:border-t-0">
          <p className="text-4xl font-semibold tabular-nums text-[#002FA7]">
            {destinations.filter((item) => item.active).length.toString().padStart(2, "0")}
          </p>
          <p className="text-xs uppercase tracking-[0.18em] text-zinc-500">Active destinations</p>
        </div>
      </div>

      <div className="grid md:grid-cols-[18rem_1fr]">
        <div className="space-y-4 border-b border-zinc-200 p-5 md:border-b-0 md:border-r">
          <div className="grid gap-1">
            <Label htmlFor="destination-kind">Identity type</Label>
            <Select
              id="destination-kind"
              value={kind}
              onChange={(event) => setKind(event.target.value as typeof kind)}
            >
              <option value="agent">Agent</option>
              <option value="service">Service</option>
              <option value="workspace">Workspace</option>
            </Select>
          </div>
          {kind !== "workspace" && (
            <div className="grid gap-1">
              <Label htmlFor="destination-scope">Owner</Label>
              <Select
                id="destination-scope"
                value={scope}
                onChange={(event) => setScope(event.target.value as typeof scope)}
              >
                <option value="personal">My account</option>
                <option value="workspace">A workspace</option>
              </Select>
            </div>
          )}
          {requiresWorkspace && (
            <div className="grid gap-1">
              <Label htmlFor="destination-workspace">Workspace</Label>
              <Select
                id="destination-workspace"
                value={workspaceSourceId}
                onChange={(event) => setWorkspaceSourceId(event.target.value)}
              >
                <option value="">Choose a workspace</option>
                {workspaceSources.map((source) => (
                  <option key={source.source_account_id} value={source.source_account_id}>
                    {source.label}
                  </option>
                ))}
              </Select>
            </div>
          )}
          <div className="grid gap-1">
            <Label htmlFor="destination-name">Display name</Label>
            <Input
              id="destination-name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Caption agent"
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="destination-slug">Public handle</Label>
            <div className="flex items-center border border-zinc-300 bg-white focus-within:border-[#002FA7]">
              <span className="border-r border-zinc-300 px-2 py-2 text-sm text-zinc-500">
                {kind}:
              </span>
              <input
                id="destination-slug"
                className="min-w-0 flex-1 bg-transparent px-2 py-2 text-sm outline-none"
                autoCapitalize="none"
                autoComplete="off"
                value={slug}
                onChange={(event) => setSlug(event.target.value.toLocaleLowerCase())}
                placeholder="caption-bot"
              />
            </div>
          </div>
          <Button
            className="w-full rounded-none bg-[#002FA7] text-white hover:bg-[#00267f]"
            disabled={!valid || submitting}
            onClick={() => void onCreate()}
          >
            {submitting ? "Creating…" : "Create destination"}
          </Button>
          {error && <p className="text-sm text-red-700">{error}</p>}
        </div>

        <div aria-live="polite">
          {loading && <p className="p-5 text-sm text-zinc-500">Loading destinations…</p>}
          {!loading && destinations.length === 0 && (
            <p className="p-5 text-sm text-zinc-500">No managed receive identities yet.</p>
          )}
          {destinations.map((destination, index) => {
            const Icon = kindIcon[destination.kind];
            const balance = balances[destination.destination_id];
            return (
              <article
                key={destination.destination_id}
                className={index === 0 ? "p-5" : "border-t border-zinc-200 p-5"}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Icon className="h-4 w-4 text-[#002FA7]" aria-hidden />
                      <p className="text-lg font-semibold tracking-tight">{destination.handle}</p>
                    </div>
                    <p className="text-sm text-zinc-600">
                      {destination.display_name} · {destination.scope}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-none"
                    onClick={() => void setDestinationActive(
                      destination.destination_id,
                      !destination.active,
                    ).catch((reason) => setError(messageOf(reason)))}
                  >
                    <Power className="mr-2 h-4 w-4" aria-hidden />
                    {destination.active ? "Disable" : "Enable"}
                  </Button>
                </div>
                <div className="mt-4 grid border-t border-zinc-200 pt-3 sm:grid-cols-[10rem_1fr] sm:gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Balance</p>
                    <p className="mt-1 font-semibold tabular-nums">
                      {balance ? formatUsdMicros(balance.available_micros) : "Unavailable"}
                    </p>
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Receive address</p>
                    <div className="mt-1 flex items-start gap-2">
                      <p className="min-w-0 break-all font-mono text-xs">{destination.address}</p>
                      <button
                        type="button"
                        aria-label={`Copy receive address for ${destination.handle}`}
                        onClick={() => void navigator.clipboard?.writeText(destination.address)}
                      >
                        <Copy className="h-4 w-4 text-zinc-500" aria-hidden />
                      </button>
                    </div>
                  </div>
                </div>
                {!destination.active && (
                  <p className="mt-3 text-xs text-red-700">
                    New transfers to this handle or address are blocked.
                  </p>
                )}
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
