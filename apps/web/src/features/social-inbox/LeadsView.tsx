"use client";

import * as React from "react";
import { ExternalLink, MessageSquare } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { RequestOptions } from "@/src/shared/api";
import {
  LEAD_STATUS_LABELS,
  cleanError,
  listLeads,
  updateLead,
  type Lead,
  type LeadStatus,
} from "./autopilot-api";
import { relativeTime } from "./format";

interface LeadsViewProps {
  getOptions: () => Promise<RequestOptions>;
  onOpenThread: (threadId: string) => void;
  onChanged: () => void;
}

const FILTERS: readonly (LeadStatus | "")[] = ["new", "contacted", "won", "dismissed", ""];

/** People whose comments or messages asked about price, ordering or availability. */
export function LeadsView({ getOptions, onOpenThread, onChanged }: Readonly<LeadsViewProps>) {
  const [filter, setFilter] = React.useState<LeadStatus | "">("new");
  const [leads, setLeads] = React.useState<readonly Lead[] | null>(null);
  const [total, setTotal] = React.useState(0);
  const [error, setError] = React.useState("");
  const [notes, setNotes] = React.useState<Readonly<Record<string, string>>>({});
  const [rowError, setRowError] = React.useState<Readonly<Record<string, string>>>({});

  const load = React.useCallback(async () => {
    setLeads(null);
    try {
      const page = await listLeads(filter, 0, await getOptions());
      setLeads(page.leads);
      setTotal(page.total);
      setNotes(Object.fromEntries(page.leads.map((l) => [l.id, l.note])));
      setError("");
    } catch (err) {
      setError(cleanError(err, "Couldn't load leads."));
      setLeads([]);
    }
  }, [filter, getOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const save = async (lead: Lead, changes: { status?: LeadStatus; note?: string }) => {
    setRowError((prev) => ({ ...prev, [lead.id]: "" }));
    try {
      const updated = await updateLead(lead.id, changes, await getOptions());
      setLeads((prev) =>
        (prev ?? [])
          .map((l) => (l.id === updated.id ? updated : l))
          .filter((l) => !filter || l.status === filter),
      );
      onChanged();
    } catch (err) {
      setRowError((prev) => ({ ...prev, [lead.id]: cleanError(err, "Couldn't save.") }));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Comments and direct messages that ask about price, ordering, shipping or availability. The autopilot
          puts them here when &quot;Send buying questions to Leads&quot; is on.
        </p>
        <div className="flex flex-wrap gap-1 rounded-lg border border-border bg-secondary/40 p-1" role="tablist">
          {FILTERS.map((f) => (
            <button
              key={f || "all"}
              type="button"
              role="tab"
              aria-selected={filter === f}
              onClick={() => setFilter(f)}
              className={
                filter === f
                  ? "rounded-md bg-background px-3 py-1 text-sm font-medium shadow-sm"
                  : "rounded-md px-3 py-1 text-sm text-muted-foreground hover:text-foreground"
              }
            >
              {f ? LEAD_STATUS_LABELS[f] : "All"}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {leads === null ? (
        <div className="space-y-2">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      ) : leads.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            {filter === "new" ? "No new leads right now." : "No leads match this filter."}
          </CardContent>
        </Card>
      ) : (
        <ul className="space-y-3">
          {total > leads.length && (
            <li className="text-xs text-muted-foreground">
              Showing {leads.length} of {total}.
            </li>
          )}
          {leads.map((lead) => (
            <li key={lead.id}>
              <Card>
                <CardContent className="space-y-3 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {lead.author_name || "Someone"}
                      <span className="font-normal text-muted-foreground">
                        {" "}
                        on {lead.platform_label}, {lead.source === "dm" ? "direct message" : "comment"},{" "}
                        {relativeTime(lead.last_message_at)}
                      </span>
                    </span>
                    <Badge variant="outline">Score {lead.score}</Badge>
                  </div>
                  <blockquote className="border-l-2 border-border pl-3 text-sm">{lead.excerpt}</blockquote>
                  {lead.signals.length > 0 && (
                    <p className="text-xs text-muted-foreground">Matched: {lead.signals.join(", ")}</p>
                  )}
                  <div className="grid gap-2 sm:grid-cols-[10rem_1fr]">
                    <Select
                      aria-label="Lead status"
                      value={lead.status}
                      onChange={(e) => void save(lead, { status: e.target.value as LeadStatus })}
                    >
                      {(Object.keys(LEAD_STATUS_LABELS) as LeadStatus[]).map((s) => (
                        <option key={s} value={s}>
                          {LEAD_STATUS_LABELS[s]}
                        </option>
                      ))}
                    </Select>
                    <Input
                      aria-label="Note"
                      placeholder="Add a note"
                      maxLength={1000}
                      value={notes[lead.id] ?? ""}
                      onChange={(e) => setNotes((prev) => ({ ...prev, [lead.id]: e.target.value }))}
                      onBlur={() => {
                        const note = notes[lead.id] ?? "";
                        if (note !== lead.note) void save(lead, { note });
                      }}
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {lead.thread_id && (
                      <Button size="sm" variant="outline" onClick={() => onOpenThread(lead.thread_id as string)}>
                        <MessageSquare className="size-4" aria-hidden /> Open conversation
                      </Button>
                    )}
                    {lead.permalink && (
                      <Button asChild size="sm" variant="ghost">
                        <a href={lead.permalink} target="_blank" rel="noopener noreferrer">
                          <ExternalLink className="size-4" aria-hidden /> Open in app
                        </a>
                      </Button>
                    )}
                  </div>
                  {rowError[lead.id] && <p className="text-xs text-destructive">{rowError[lead.id]}</p>}
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
