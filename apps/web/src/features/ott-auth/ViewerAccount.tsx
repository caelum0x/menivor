"use client";

import * as React from "react";
import Link from "next/link";
import { continueWatching, deleteMe, exchange, myPurchases, signOutEverywhere, type ProgressView, type PurchaseView } from "./api";
import { ottSurfaceLive } from "@/src/features/ott-player/flags";
import { requestCode, SignInError, verifyCode } from "./scribase-auth";
import { clearSession, readSession, writeSession, type StoredSession } from "./session-store";

function message(err: unknown): string {
  return err instanceof Error && err.message ? err.message : "Something went wrong. Try again.";
}

/** Email, then the code from the email: two steps, then the viewer is signed in to this channel. */
export function ViewerSignIn({ handle, onSignedIn }: Readonly<{ handle: string; onSignedIn: (s: StoredSession) => void }>) {
  const [email, setEmail] = React.useState("");
  const [code, setCode] = React.useState("");
  const [sent, setSent] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (!sent) {
        await requestCode(email);
        setSent(true);
      } else {
        const token = await verifyCode(email, code);
        const result = await exchange(handle, token);
        const stored = { session: result.session, expiresAt: result.expires_at, name: result.viewer.display_name };
        writeSession(handle, stored);
        onSignedIn(stored);
      }
    } catch (err) {
      setError(err instanceof SignInError ? err.message : message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2" aria-label="Sign in to this channel">
      {!sent ? (
        <label className="text-sm">
          Email
          <input className="ml-2 rounded-lg border px-2 py-1" type="email" required value={email}
            onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </label>
      ) : (
        <label className="text-sm">
          Code from your email
          <input className="ml-2 w-28 rounded-lg border px-2 py-1" inputMode="numeric" required value={code}
            onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" />
        </label>
      )}
      <button type="submit" className="rounded-lg bg-foreground px-3 py-1 text-sm text-background" disabled={busy}>
        {sent ? "Sign in" : "Send code"}
      </button>
      {error ? <p role="alert" className="w-full text-sm">{error}</p> : null}
    </form>
  );
}

/** The channel account bar: sign in, continue watching, sign out everywhere, delete my account. */
export function ViewerAccount({ handle }: Readonly<{ handle: string }>) {
  const [session, setSession] = React.useState<StoredSession | null>(null);
  const [items, setItems] = React.useState<readonly ProgressView[]>([]);
  const [purchases, setPurchases] = React.useState<readonly PurchaseView[]>([]);
  const [confirming, setConfirming] = React.useState(false);
  const [notice, setNotice] = React.useState("");

  React.useEffect(() => setSession(readSession(handle)), [handle]);

  React.useEffect(() => {
    if (!session) return;
    let live = true;
    continueWatching(handle, session.session)
      .then((data) => live && setItems(data.items))
      .catch((err) => {
        if (!live) return;
        if ((err as { status?: number }).status === 401) {
          clearSession(handle);
          setSession(null);
        }
      });
    if (ottSurfaceLive("commerce")) {
      myPurchases(handle, session.session)
        .then((data) => live && setPurchases(data.items.filter((p) => p.status === "active")))
        .catch(() => undefined);
    }
    return () => {
      live = false;
    };
  }, [handle, session]);

  if (!session) {
    return (
      <section className="mb-6" aria-label="Your account">
        <ViewerSignIn handle={handle} onSignedIn={setSession} />
        {notice ? <p className="mt-2 text-sm">{notice}</p> : null}
      </section>
    );
  }

  const signOut = async () => {
    await signOutEverywhere(handle, session.session).catch(() => undefined);
    clearSession(handle);
    setSession(null);
  };
  const remove = async () => {
    try {
      await deleteMe(handle, session.session);
      clearSession(handle);
      setSession(null);
      setNotice("Your account and watch history on this channel were deleted.");
    } catch (err) {
      setNotice(message(err));
    }
  };

  return (
    <section className="mb-6 space-y-3" aria-label="Your account">
      <p className="text-sm">Signed in as {session.name}</p>
      {items.length ? (
        <div>
          <h2 className="mb-2 text-base font-semibold">Continue watching</h2>
          <ul className="flex gap-3 overflow-x-auto">
            {items.map((item) => (
              <li key={item.title_id}>
                <Link className="underline" href={`/c/${encodeURIComponent(handle)}/${encodeURIComponent(item.title_id)}`}>
                  {item.title}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {purchases.length ? (
        <p className="text-sm">
          Yours: {purchases.map((p) => (p.expires_at ? `${p.offer} (until ${new Date(p.expires_at).toLocaleString()})` : p.offer)).join(", ")}
        </p>
      ) : null}
      <div className="flex gap-3 text-sm">
        <button type="button" className="underline" onClick={signOut}>Sign out on all devices</button>
        {confirming ? (
          <>
            <button type="button" className="underline" onClick={remove}>Yes, delete my account and history</button>
            <button type="button" className="underline" onClick={() => setConfirming(false)}>Keep it</button>
          </>
        ) : (
          <button type="button" className="underline" onClick={() => setConfirming(true)}>Delete my account</button>
        )}
      </div>
      {notice ? <p role="status" className="text-sm">{notice}</p> : null}
    </section>
  );
}
