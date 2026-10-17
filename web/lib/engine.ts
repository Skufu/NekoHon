export type FigureCard = {
  id: string;
  chapter: string;
  caption: string;
  src: string;
  width?: number;
  height?: number;
};

export type Chunk = {
  chunk_id: string;
  chapter: string;
  heading: string;
  section: string;
  source: string;
  text: string;
  figures: FigureCard[];
};

export type Citation = { chunk_id: string; chapter: string; quote: string };

export type AnswerBody = {
  answer: string;
  citations: Citation[];
  figures: FigureCard[];
  refused: boolean;
  error?: string;
};

export type ChunksPayload = { book_id: string; chunks: Chunk[] };

export function engineUrl(): string {
  if (process.env.NEXT_PUBLIC_ENGINE_URL) return process.env.NEXT_PUBLIC_ENGINE_URL;
  // Anything that is not the engine's own port (8000) is a dev or preview
  // server: call the engine where it lives. Served by the engine = same origin.
  if (typeof window !== "undefined" && window.location.port !== "8000") {
    return "http://127.0.0.1:8000";
  }
  return "";
}

export async function fetchChunks(): Promise<ChunksPayload> {
  const response = await fetch(`${engineUrl()}/chunks`);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.error || `engine returned ${response.status}`);
  }
  return response.json();
}

export type AskRequest = {
  mode: string;
  question?: string;
  selection?: string;
  chunk_id?: string;
  end_chunk_id?: string;
  heading?: string;
  history?: { question: string; answer: string }[];
  stream?: number;
};

type StreamHandlers = {
  onToken(text: string): void;
  onReset(): void;
  onFinal(body: AnswerBody): void;
  onError(message: string): void;
};

export async function askStream(
  payload: AskRequest,
  handlers: StreamHandlers,
  signal: AbortSignal
): Promise<void> {
  const response = await fetch(`${engineUrl()}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, stream: 1 }),
    signal,
  });
  if (!response.ok || !response.body) {
    let message = `engine returned ${response.status}`;
    try {
      const data = await response.json();
      if (data?.error) message = data.error;
    } catch {
      // the body was not JSON; keep the status line
    }
    handlers.onError(message);
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawTerminalFrame = false;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index: number;
    while ((index = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, index).trim();
      buffer = buffer.slice(index + 1);
      if (!line) continue;
      let frame: { type?: string; text?: string; body?: AnswerBody; error?: string };
      try {
        frame = JSON.parse(line);
      } catch {
        continue;
      }
      if (frame.type === "token" && typeof frame.text === "string") {
        handlers.onToken(frame.text);
      } else if (frame.type === "reset") {
        handlers.onReset();
      } else if (frame.type === "final" && frame.body) {
        sawTerminalFrame = true;
        handlers.onFinal(frame.body);
      } else if (frame.type === "error") {
        sawTerminalFrame = true;
        handlers.onError(frame.error || "engine error");
      }
    }
  }
  if (!sawTerminalFrame) {
    // EOF with no final/error frame (engine crash or dropped socket): without
    // this the pane stays blank and the store's controller is never cleared.
    handlers.onError(
      "The connection dropped before the answer finished — ask again."
    );
  }
}
