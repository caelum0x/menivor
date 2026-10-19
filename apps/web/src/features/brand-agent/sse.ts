/**
 * Minimal Server-Sent Events parser for the agent stream (`event:` + `data:` frames).
 * Pure: feed it text chunks, it returns the complete events and keeps the remainder.
 */

export interface SseEvent {
  event: string;
  data: unknown;
}

export interface SseParser {
  push(chunk: string): SseEvent[];
}

function parseFrame(frame: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (dataLines.length === 0) return null;
  const raw = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(raw) as unknown };
  } catch {
    return { event, data: raw };
  }
}

export function createSseParser(): SseParser {
  let buffer = "";
  return {
    push(chunk: string): SseEvent[] {
      buffer += chunk.replace(/\r\n/g, "\n");
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      return frames.map(parseFrame).filter((e): e is SseEvent => e !== null);
    },
  };
}
