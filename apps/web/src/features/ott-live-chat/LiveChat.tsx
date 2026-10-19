"use client";

import * as React from "react";
import { readSession, ViewerSignIn, type StoredSession } from "@/src/features/ott-auth";
import { postChat, readChat } from "./api";
import { subscribe, type ChatMessage } from "./realtime";

export const POLL_MS = 4000;
const MAX_SHOWN = 200;

function merge(list: readonly ChatMessage[], incoming: readonly ChatMessage[]): ChatMessage[] {
  const seen = new Set(list.map((m) => m.id));
  return [...list, ...incoming.filter((m) => !seen.has(m.id))].slice(-MAX_SHOWN);
}

/** Live chat: realtime when the socket is up, polling when it is not; posting needs a channel sign-in. */
export function LiveChat({ handle, streamId }: Readonly<{ handle: string; streamId: string }>) {
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [session, setSession] = React.useState<StoredSession | null>(null);
  const [live, setLive] = React.useState(false);
  const [text, setText] = React.useState("");
  const [error, setError] = React.useState("");
  const lastAt = React.useRef<string | undefined>(undefined);

  React.useEffect(() => setSession(readSession(handle)), [handle]);
  React.useEffect(() => {
    lastAt.current = messages[messages.length - 1]?.at ?? undefined;
  }, [messages]);

  React.useEffect(() => {
    let active = true;
    void readChat(streamId).then((data) => active && setMessages(data.messages)).catch(() => undefined);
    const url = process.env.NEXT_PUBLIC_SCRIBASE_VIEWERS_URL ?? "";
    const key = process.env.NEXT_PUBLIC_SCRIBASE_VIEWERS_ANON_KEY ?? "";
    if (!url || !key || typeof WebSocket === "undefined") return () => {
      active = false;
    };
    const stop = subscribe(url, key, `ott-live:${streamId}`, {
      onChat: (m) => setMessages((list) => merge(list, [m])),
      onHide: (id) => setMessages((list) => list.filter((m) => m.id !== id)),
      onState: setLive,
    });
    return () => {
      active = false;
      stop();
    };
  }, [streamId]);

  React.useEffect(() => {
    if (live) return undefined;
    const timer = setInterval(() => {
      void readChat(streamId, lastAt.current)
        .then((data) => setMessages((current) => merge(current, data.messages)))
        .catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [live, streamId]);

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!session) return;
    setError("");
    try {
      const sent = await postChat(streamId, session.session, text);
      setMessages((list) => merge(list, [sent]));
      setText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Your message was not sent.");
    }
  };

  return (
    <section aria-label="Live chat" className="flex h-full flex-col gap-2 rounded-xl border border-border p-3">
      <ol className="flex-1 space-y-1 overflow-y-auto text-sm" aria-live="polite">
        {messages.map((m) => (
          <li key={m.id}><span className="font-semibold">{m.name}</span> {m.body}</li>
        ))}
      </ol>
      {session ? (
        <form onSubmit={send} className="flex gap-2">
          <label className="sr-only" htmlFor={`chat-${streamId}`}>Message</label>
          <input id={`chat-${streamId}`} className="flex-1 rounded-lg border px-2 py-1" maxLength={300} value={text}
            onChange={(e) => setText(e.target.value)} />
          <button type="submit" className="rounded-lg bg-foreground px-3 py-1 text-sm text-background">Send</button>
        </form>
      ) : (
        <ViewerSignIn handle={handle} onSignedIn={setSession} />
      )}
      {error ? <p role="alert" className="text-sm">{error}</p> : null}
    </section>
  );
}
