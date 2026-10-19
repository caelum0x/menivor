"use client";

import * as React from "react";
import { ArrowLeftRight, Check, CircleAlert, Clock, Coins, Send, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { AgentAction, AgentCard } from "./api";

type Data = Record<string, unknown>;

const asList = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const asText = (v: unknown): string => (typeof v === "string" ? v : "");
const asData = (v: unknown): Data => (v && typeof v === "object" ? (v as Data) : {});

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function Positioning({ data }: { data: Data }) {
  const colors = asList(data.colors).map(asText).filter(Boolean);
  const fonts = asList(data.fonts).map(asText).filter(Boolean);
  const logo = asText(data.logo_url);
  return (
    <dl className="grid gap-3 sm:grid-cols-2">
      <Field label="Category">{asText(data.category) || "Not found"}</Field>
      <Field label="Pricing hook">{asText(data.pricing_hook) || "Not found"}</Field>
      <div className="sm:col-span-2">
        <Field label="Positioning">{asText(data.one_liner) || "Not found"}</Field>
      </div>
      <Field label="Brand colors">
        <span className="flex flex-wrap gap-2">
          {colors.length === 0 && "Not found"}
          {colors.map((hex) => (
            <span key={hex} className="inline-flex items-center gap-1 font-mono text-xs">
              <span className="size-4 rounded-full border border-border" style={{ backgroundColor: hex }} aria-hidden />
              {hex}
            </span>
          ))}
        </span>
      </Field>
      <Field label="Fonts">{fonts.join(", ") || "Not found"}</Field>
      {logo && (
        <Field label="Logo">
          {/* eslint-disable-next-line @next/next/no-img-element -- remote brand logo, any host */}
          <img src={logo} alt="Detected logo" className="h-10 w-auto rounded bg-white/5 p-1" />
        </Field>
      )}
    </dl>
  );
}

function Products({ data }: { data: Data }) {
  return (
    <div className="space-y-3">
      {asList(data.products).map((raw, i) => {
        const p = asData(raw);
        return (
          <div key={i} className="space-y-1">
            <p className="font-medium">{asText(p.name)}</p>
            <p className="text-sm text-muted-foreground">{asText(p.what_it_is)}</p>
            <ul className="flex flex-wrap gap-2 pt-1">
              {asList(p.key_features).map((f) => (
                <li key={asText(f)}>
                  <Badge variant="secondary">{asText(f)}</Badge>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function Market({ data }: { data: Data }) {
  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {asList(data.competitors).map((raw, i) => {
          const c = asData(raw);
          const switchSource = c.relationship === "switch_source";
          return (
            <li key={i} className="flex items-start gap-2 text-sm">
              <ArrowLeftRight className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span>
                <span className="font-medium">{asText(c.name)}</span>
                {switchSource && (
                  <Badge variant="outline" className="ml-2">
                    Where switchers come from
                  </Badge>
                )}
                {asText(c.note) && <span className="block text-muted-foreground">{asText(c.note)}</span>}
              </span>
            </li>
          );
        })}
      </ul>
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
        {asList(data.insights).map((x) => (
          <li key={asText(x)}>{asText(x)}</li>
        ))}
      </ul>
    </div>
  );
}

function Voice({ data }: { data: Data }) {
  return (
    <div className="space-y-3">
      <Field label="Sample lines">
        <ul className="space-y-1">
          {asList(data.sample_lines).slice(0, 4).map((l) => (
            <li key={asText(l)} className="italic text-muted-foreground">
              &ldquo;{asText(l)}&rdquo;
            </li>
          ))}
        </ul>
      </Field>
      <Field label="Audience">
        <ul className="space-y-2">
          {asList(data.segments).map((raw, i) => {
            const seg = asData(raw);
            return (
              <li key={i}>
                <span className="font-medium">{asText(seg.name)}</span>
                <span className="block text-muted-foreground">{asList(seg.pains).map(asText).join("; ")}</span>
              </li>
            );
          })}
        </ul>
      </Field>
    </div>
  );
}

const STATUS_ICON = {
  executed: Check,
  rejected: X,
  failed: X,
  pending: Clock,
  approved: Clock,
  blocked: CircleAlert,
} as const;
const STATUS_LABEL: Record<string, string> = { blocked: "needs one step" };

export function ActionSummary({ action }: { action: AgentAction }) {
  const Icon = STATUS_ICON[action.status] ?? Clock;
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <Icon className="size-4 text-muted-foreground" aria-hidden />
      <span className="font-medium">{action.title}</span>
      {action.spends_credits && action.credits_estimate > 0 && (
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <Coins className="size-4" aria-hidden /> about {action.credits_estimate} credits
        </span>
      )}
      {action.publishes && (
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <Send className="size-4" aria-hidden /> publishes
        </span>
      )}
      <Badge variant={action.status === "failed" ? "destructive" : "secondary"}>
        {STATUS_LABEL[action.status] ?? action.status}
      </Badge>
      {action.error && <span className="w-full text-destructive">{action.error}</span>}
      {action.status === "blocked" && (action.needs?.length ?? 0) > 0 && (
        <ul className="w-full space-y-1" aria-label="Before you can approve">
          {action.needs!.map((n) => (
            <li key={n.id} className="text-sm">
              <span className="font-medium">{n.title}</span>
              {n.detail && <span className="block text-muted-foreground">{n.detail}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Structured body of an assistant message (setup step, hooks, script, action...). */
export function MessageCard({ card, action }: { card: AgentCard; action: AgentAction | null }) {
  const data = card.data ?? {};
  let body: React.ReactNode = null;
  if (card.type === "setup_step") {
    body =
      card.step === "positioning" ? (
        <Positioning data={data} />
      ) : card.step === "product" ? (
        <Products data={data} />
      ) : card.step === "market" ? (
        <Market data={data} />
      ) : (
        <Voice data={data} />
      );
  } else if (card.type === "hooks") {
    body = (
      <ol className="list-decimal space-y-1 pl-5 text-sm">
        {asList(data.hooks).map((h) => (
          <li key={asText(h)}>{asText(h)}</li>
        ))}
      </ol>
    );
  } else if (card.type === "script") {
    body = (
      <ol className="space-y-1 text-sm">
        {asList(data.lines).map((l, i) => (
          <li key={i}>{asText(l)}</li>
        ))}
      </ol>
    );
  } else if (card.type === "action" && action) {
    body = <ActionSummary action={action} />;
  } else if (card.type === "routine") {
    body = (
      <p className="text-sm text-muted-foreground">
        Next run: {asText(data.next_run_at) ? new Date(asText(data.next_run_at)).toUTCString() : "soon"}
      </p>
    );
  }
  if (!body) return null;
  return (
    <div className="glass-subtle mt-2 space-y-2 rounded-xl border border-border p-4">
      {card.title && (
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {card.title}
          {card.index ? ` · step ${card.index} of ${card.total}` : ""}
        </p>
      )}
      {body}
    </div>
  );
}
