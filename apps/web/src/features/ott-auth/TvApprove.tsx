"use client";

import * as React from "react";
import { approveTvCode } from "./api";
import { readSession, type StoredSession } from "./session-store";
import { ViewerSignIn } from "./ViewerAccount";

/** On the phone: sign in to the channel (if needed), type the code the TV shows, and the TV signs in. */
export function TvApprove({ handle }: Readonly<{ handle: string }>) {
  const [session, setSession] = React.useState<StoredSession | null>(null);
  const [code, setCode] = React.useState("");
  const [done, setDone] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => setSession(readSession(handle)), [handle]);

  if (!session) return <ViewerSignIn handle={handle} onSignedIn={setSession} />;
  if (done) return <p role="status">Your TV is signed in. You can put your phone away.</p>;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await approveTvCode(handle, session.session, code);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "That code did not work.");
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2" aria-label="Sign in your TV">
      <label className="text-sm">
        Code on your TV
        <input className="ml-2 w-32 rounded-lg border px-2 py-1 uppercase tracking-widest" required value={code}
          onChange={(e) => setCode(e.target.value)} autoComplete="off" />
      </label>
      <button type="submit" className="rounded-lg bg-foreground px-3 py-1 text-sm text-background">Sign in TV</button>
      {error ? <p role="alert" className="w-full text-sm">{error}</p> : null}
    </form>
  );
}
