"use client";

import * as React from "react";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { banViewer, createStream, hideMessage, listStreams, rotateKey, setSlowMode, studioChat, type StudioStream } from "./api";

type Moderated = { id: string; name: string; body: string; viewer_id: string; hidden: boolean };

/** Go live from OBS: create a stream, copy the server and key (shown once), moderate chat. */
export function StudioLive() {
  const getApiToken = useApiToken();
  const [streams, setStreams] = React.useState<readonly StudioStream[]>([]);
  const [created, setCreated] = React.useState<StudioStream | null>(null);
  const [title, setTitle] = React.useState("");
  const [open, setOpen] = React.useState<string | null>(null);
  const [chat, setChat] = React.useState<readonly Moderated[]>([]);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      setStreams((await listStreams({ token: await getApiToken() })).streams);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Live streams could not load."));
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      setCreated(await createStream(title, { token: await getApiToken() }));
      setTitle("");
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "The stream could not be created."));
    }
  };
  const moderate = async (streamId: string) => {
    setOpen(streamId);
    setChat((await studioChat(streamId, { token: await getApiToken() })).messages);
  };

  return (
    <section aria-label="Go live" className="space-y-3 rounded-xl border border-border p-3">
      <h2 className="text-sm font-semibold">Go live</h2>
      <form onSubmit={create} className="flex gap-2 text-sm">
        <label>Stream title<input className="ml-2 rounded border px-2 py-1" required value={title}
          onChange={(e) => setTitle(e.target.value)} /></label>
        <button type="submit" className="rounded-lg border px-3 py-1">Create stream</button>
      </form>
      {created?.ingest ? (
        <div className="space-y-1 rounded-lg bg-muted p-2 text-sm" data-ingest>
          <p>In OBS, set Server to <code>{created.ingest.server}</code> and Stream key to <code>{created.ingest.stream_key}</code>.</p>
          <p>Copy the key now. It is not shown again.</p>
        </div>
      ) : null}
      <ul className="space-y-2 text-sm">
        {streams.map((s) => (
          <li key={s.id} data-stream={s.id}>
            {s.title}: {s.status}
            {s.latency_s ? `, about ${s.latency_s.median} s behind (measured)` : ""}
            {s.peak_viewers ? `, ${s.peak_viewers} viewers at most` : ""}{" "}
            <button type="button" className="underline" onClick={() => void moderate(s.id)}>Chat</button>{" "}
            {s.status !== "live" ? (
              <button type="button" className="underline" onClick={async () => {
                try {
                  const { ingest } = await rotateKey(s.id, { token: await getApiToken() });
                  setCreated({ ...s, ingest });
                } catch (err) {
                  setError(friendlyErrorMessage(err, "A new key could not be made."));
                }
              }}>New key</button>
            ) : null}
          </li>
        ))}
      </ul>
      {open ? (
        <div className="space-y-2 text-sm">
          <button type="button" className="underline" onClick={async () => {
            await setSlowMode(open, 10, { token: await getApiToken() }).catch(() => undefined);
          }}>Slow mode 10 s</button>
          <ol className="space-y-1">
            {chat.filter((m) => !m.hidden).map((m) => (
              <li key={m.id}>
                <span className="font-semibold">{m.name}</span> {m.body}{" "}
                <button type="button" className="underline" onClick={async () => {
                  await hideMessage(open, m.id, { token: await getApiToken() }).catch(() => undefined);
                  await moderate(open);
                }}>Remove</button>{" "}
                <button type="button" className="underline" onClick={async () => {
                  await banViewer(open, m.viewer_id, { token: await getApiToken() }).catch(() => undefined);
                  await moderate(open);
                }}>Ban</button>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {error ? <p role="alert" className="text-sm">{error}</p> : null}
    </section>
  );
}
