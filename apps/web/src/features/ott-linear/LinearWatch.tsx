"use client";

import * as React from "react";
import { attach, soundFocus, type Attached } from "@menivor/ott-player";
import type { NowView } from "./api";

const loadHls = async () => (await import("hls.js")).default as unknown as import("@menivor/ott-player").HlsConstructor;

/** Watch a Always-on channel: what is on now, what is next, and the stream. */
export function LinearWatch({ view }: Readonly<{ view: NowView }>) {
  const video = React.useRef<HTMLVideoElement>(null);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    const el = video.current;
    if (!el) return undefined;
    let attached: Attached | null = null;
    const unregister = soundFocus.register(el);
    void attach(el, view.watch_url, loadHls, (reason) => setError(`The channel stopped: ${reason}.`))
      .then((a) => {
        attached = a;
      })
      .catch(() => setError("This channel could not start."));
    return () => {
      unregister();
      attached?.destroy();
    };
  }, [view.watch_url]);
  return (
    <div className="space-y-3">
      <video ref={video} className="aspect-video w-full rounded-2xl bg-black" controls playsInline />
      <p className="text-sm">Now: {view.now.kind === "ad" ? "A short break" : view.now.title}</p>
      {view.next.length ? (
        <ul className="text-sm text-muted-foreground">
          {view.next.map((n) => <li key={n.start}>{new Date(n.start).toLocaleTimeString()}: {n.title}</li>)}
        </ul>
      ) : null}
      {error ? <p role="alert" className="text-sm">{error}</p> : null}
    </div>
  );
}
