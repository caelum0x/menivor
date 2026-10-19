"use client";

import * as React from "react";
import { clock } from "@/src/features/ott-ai/api";
import { askVideo, type AskAnswer } from "./api";

/** Ask this video: the answer comes from what is said in it, with the time to jump to, or an honest "I do not know". */
export function AskVideo({ titleId }: Readonly<{ titleId: string }>) {
  const [question, setQuestion] = React.useState("");
  const [answer, setAnswer] = React.useState<AskAnswer | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setAnswer(await askVideo(titleId, question));
    } catch (err) {
      setError(err instanceof Error ? err.message : "That question could not be answered right now.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Ask this video" className="mt-6 space-y-2 text-sm">
      <form onSubmit={submit} className="flex gap-2">
        <label className="flex-1">
          <span className="sr-only">Ask this video</span>
          <input className="w-full rounded-lg border px-3 py-2" placeholder="Ask this video" minLength={3} maxLength={300}
            required value={question} onChange={(e) => setQuestion(e.target.value)} />
        </label>
        <button type="submit" className="rounded-lg border px-3 py-2" disabled={busy}>Ask</button>
      </form>
      {answer ? (
        <div role="status">
          <p>{answer.answer}</p>
          {answer.citations.map((c) => (
            <p key={c.start_s} className="text-muted-foreground">At {clock(c.start_s)}: {`"${c.text}"`}</p>
          ))}
        </div>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}
