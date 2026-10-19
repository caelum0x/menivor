/**
 * Live chat over Scribase Realtime (MV11, dogfood). A small Phoenix-channel
 * client for broadcast topics: join, heartbeat every 25 s, deliver `chat` and
 * `hide` events. If the socket cannot open or drops, the caller falls back to
 * polling `GET /ott/live/{id}/chat`.
 */

export interface ChatMessage {
  readonly id: string;
  readonly name: string;
  readonly body: string;
  readonly at: string | null;
}

export interface RealtimeHandlers {
  readonly onChat: (message: ChatMessage) => void;
  readonly onHide: (id: string) => void;
  readonly onState: (open: boolean) => void;
}

type SocketLike = Pick<WebSocket, "send" | "close" | "readyState"> & {
  onopen: ((ev: Event) => void) | null;
  onclose: ((ev: CloseEvent) => void) | null;
  onerror: ((ev: Event) => void) | null;
  onmessage: ((ev: MessageEvent) => void) | null;
};

export const HEARTBEAT_MS = 25_000;

export function socketUrl(projectUrl: string, anonKey: string): string {
  const base = projectUrl.replace(/\/+$/, "").replace(/^http/, "ws");
  return `${base}/realtime/v1/websocket?apikey=${encodeURIComponent(anonKey)}&vsn=1.0.0`;
}

export function subscribe(
  projectUrl: string,
  anonKey: string,
  topic: string,
  handlers: RealtimeHandlers,
  makeSocket: (url: string) => SocketLike = (url) => new WebSocket(url) as unknown as SocketLike,
): () => void {
  let ref = 0;
  const next = () => String(++ref);
  const channel = `realtime:${topic}`;
  const socket = makeSocket(socketUrl(projectUrl, anonKey));
  let beat: ReturnType<typeof setInterval> | undefined;
  const send = (payload: unknown) => {
    if (socket.readyState === 1) socket.send(JSON.stringify(payload));
  };
  socket.onopen = () => {
    const join = next();
    send({ topic: channel, event: "phx_join", ref: join, join_ref: join,
      payload: { config: { broadcast: { ack: false, self: false }, presence: { key: "" }, private: false } } });
    beat = setInterval(() => send({ topic: "phoenix", event: "heartbeat", payload: {}, ref: next() }), HEARTBEAT_MS);
    handlers.onState(true);
  };
  socket.onmessage = (event) => {
    let frame: { topic?: string; event?: string; payload?: { event?: string; payload?: unknown } };
    try {
      frame = JSON.parse(String(event.data));
    } catch {
      return;
    }
    if (frame.topic !== channel || frame.event !== "broadcast") return;
    const inner = frame.payload;
    if (inner?.event === "chat") handlers.onChat(inner.payload as ChatMessage);
    if (inner?.event === "hide") handlers.onHide(String((inner.payload as { id?: string })?.id ?? ""));
  };
  const down = () => {
    if (beat) clearInterval(beat);
    handlers.onState(false);
  };
  socket.onclose = down;
  socket.onerror = down;
  return () => {
    if (beat) clearInterval(beat);
    socket.onclose = null;
    socket.close();
  };
}
