"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUp, Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { getSession, streamTurn, type AgentMessage, type Chip } from "./api";
import { MessageCard } from "./MessageCard";
import { ProductPicker } from "./ProductPicker";

export const SETUP_PROMPT = "Let's set up my brand from my website: ";

export interface ChatViewProps {
  sessionId: string;
  /** Called after any turn so the sidebar can refresh its Brain badge and counts. */
  onTurn?: () => void;
  /** Text to place in the composer (for example a skill's starter prompt). */
  prefill?: string;
}

function localUser(text: string): AgentMessage {
  return {
    id: `local-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    seq: Number.MAX_SAFE_INTEGER,
    role: "user",
    content: text,
    card: null,
    chips: [],
    action_id: null,
    action: null,
    created_at: null,
  };
}

/** The blocked action's product step, when it has products to pick from. */
function productNeed(m: AgentMessage) {
  if (m.action?.status !== "blocked") return null;
  const need = m.action.needs?.find((n) => n.id === "product");
  return need && need.options.length > 0 ? need : null;
}

/** Product chips become the picker; every other chip stays a button or link. */
function visibleChips(m: AgentMessage): Chip[] {
  return productNeed(m) ? m.chips.filter((c) => c.choice !== "use_product") : m.chips;
}

/** One agent conversation: messages, Yes/No and Approve/Reject chips, and the composer. */
export function ChatView({ sessionId, onTurn, prefill }: ChatViewProps) {
  const requestOptions = useRequestOptions();
  const [messages, setMessages] = React.useState<AgentMessage[]>([]);
  const [drafts, setDrafts] = React.useState<Record<string, string>>({});
  const [answered, setAnswered] = React.useState<Set<string>>(new Set());
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const endRef = React.useRef<HTMLDivElement | null>(null);

  // Load once per session; the token getter may change identity between renders.
  const optionsRef = React.useRef(requestOptions);
  optionsRef.current = requestOptions;

  React.useEffect(() => {
    let live = true;
    (async () => {
      try {
        const out = await getSession(sessionId, await optionsRef.current());
        if (live) {
          setMessages(out.messages);
          setAnswered(new Set(out.messages.slice(0, -1).map((m) => m.id)));
        }
      } catch (err) {
        if (live) setError(errorMessage(err));
      }
    })();
    return () => {
      live = false;
    };
  }, [sessionId]);

  React.useEffect(() => {
    if (prefill) setText(prefill);
  }, [prefill]);

  React.useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages, drafts]);

  const turn = async (body: Parameters<typeof streamTurn>[1], echo: string, answeredId?: string) => {
    setBusy(true);
    setError("");
    setMessages((prev) => [...prev, localUser(echo)]);
    if (answeredId) setAnswered((prev) => new Set(prev).add(answeredId));
    try {
      await streamTurn(
        sessionId,
        body,
        {
          onDelta: (id, chunk) => setDrafts((prev) => ({ ...prev, [id]: (prev[id] ?? "") + chunk })),
          onMessage: (message) => {
            setDrafts((prev) => {
              const next = { ...prev };
              delete next[message.id];
              return next;
            });
            setMessages((prev) => [...prev, message]);
          },
        },
        await requestOptions(),
      );
      onTurn?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setText("");
    void turn({ text: value }, value);
  };

  const pick = (message: AgentMessage, chip: Chip) => {
    if (busy || chip.choice === "open") return;
    void turn(
      { choice: chip.choice, step: chip.step ?? "", action_id: chip.action_id, value: chip.value },
      chip.label,
      message.id,
    );
  };

  const empty = messages.length === 0;

  return (
    <div className="flex h-[calc(100dvh-7.5rem)] min-h-[24rem] flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto pb-4" aria-live="polite">
        {empty && (
          <div className="glass-subtle mx-auto mt-10 max-w-lg space-y-3 rounded-2xl border border-border p-6 text-center">
            <Sparkles className="mx-auto size-6 text-primary" aria-hidden />
            <h2 className="text-lg font-semibold">Set up your brand</h2>
            <p className="text-sm text-muted-foreground">
              Paste your website. I read your colors, fonts, logo and copy, look at your market, and confirm each part
              with you before saving it to brand memory.
            </p>
            <Button type="button" variant="outline" size="sm" onClick={() => setText(SETUP_PROMPT)}>
              Start from my website
            </Button>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={
                m.role === "user"
                  ? "max-w-[80%] rounded-2xl bg-primary/15 px-4 py-2 text-sm"
                  : "max-w-[92%] space-y-2 text-sm"
              }
            >
              <p className="whitespace-pre-wrap">{m.content}</p>
              {m.card && <MessageCard card={m.card} action={m.action} />}
              {productNeed(m) && !answered.has(m.id) && (
                <ProductPicker
                  options={productNeed(m)!.options}
                  disabled={busy}
                  onPick={(o) =>
                    pick(m, { label: `Use ${o.name}`, choice: "use_product", action_id: m.action!.id, value: o.id })
                  }
                />
              )}
              {visibleChips(m).length > 0 && !answered.has(m.id) && (
                <div className="flex flex-wrap gap-2 pt-1" role="group" aria-label="Answer">
                  {visibleChips(m).map((chip, i) =>
                    chip.choice === "open" && chip.href ? (
                      <Button key={`open-${chip.href}`} asChild size="sm" variant={i === 0 ? "secondary" : "outline"}>
                        <Link href={chip.href}>{chip.label}</Link>
                      </Button>
                    ) : (
                      <Button
                        key={`${chip.choice}-${chip.action_id ?? chip.step}-${chip.value ?? ""}`}
                        type="button"
                        size="sm"
                        variant={i === 0 ? "secondary" : "outline"}
                        disabled={busy}
                        onClick={() => pick(m, chip)}
                      >
                        {chip.label}
                      </Button>
                    ),
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {Object.entries(drafts).map(([id, draft]) => (
          <p key={id} className="max-w-[92%] whitespace-pre-wrap text-sm">
            {draft}
          </p>
        ))}
        {busy && Object.keys(drafts).length === 0 && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Working
          </p>
        )}
        <div ref={endRef} />
      </div>
      <ErrorText message={error} />
      <form onSubmit={submit} className="glass flex items-end gap-2 rounded-2xl border border-border p-2">
        <label htmlFor="agent-composer" className="sr-only">
          Message the agent
        </label>
        <Textarea
          id="agent-composer"
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) submit(e);
          }}
          placeholder="Ask for hooks, a script, an image or video ad, or paste an ad link to clone"
          className="min-h-0 resize-none border-0 bg-transparent focus-visible:ring-0"
          disabled={busy}
        />
        <Button type="submit" size="icon" disabled={busy || !text.trim()} aria-label="Send">
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <ArrowUp className="size-4" aria-hidden />}
        </Button>
      </form>
    </div>
  );
}
