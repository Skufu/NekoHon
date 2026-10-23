type FigureCard = {
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
  followups?: string[];
};

export type BookCatalogItem = {
  book_id: string;
  title: string;
  author: string;
  chapter_count: number;
  chunk_count: number;
  figure_count: number;
  cover_url?: string;
};

export type ChunksPayload = {
  book_id: string;
  chunks: Chunk[];
  title?: string;
  author?: string;
  books?: BookCatalogItem[];
};

type HealthResponse = {
  ok?: boolean;
  ready?: boolean;
  ollama?: boolean;
  book_id?: string;
  books?: BookCatalogItem[];
};

export function engineUrl(): string {
  if (process.env.NEXT_PUBLIC_ENGINE_URL) return process.env.NEXT_PUBLIC_ENGINE_URL;
  // Next.js dev server runs on :3100 (hot reload). Target the engine on :8000.
  // When served by the engine (production static export on :8000, :8020, etc.),
  // the page is same-origin, so use relative URLs ("").
  if (typeof window !== "undefined" && window.location.port === "3100") {
    return "http://127.0.0.1:8000";
  }
  return "";
}

const chunksCache = new Map<string, ChunksPayload>();
const chunksInFlight = new Map<string, Promise<ChunksPayload>>();

export function prefetchChunks(bookId = "fde"): void {
  if (chunksCache.has(bookId) || chunksInFlight.has(bookId)) return;
  fetchChunks(bookId).catch(() => {});
}

export async function checkHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${engineUrl()}/health`, { signal });
  if (!response.ok) {
    throw new Error(`health check failed with status ${response.status}`);
  }
  return await response.json();
}

export async function fetchChunks(
  bookId = "fde",
  signal?: AbortSignal
): Promise<ChunksPayload> {
  const cached = chunksCache.get(bookId);
  if (cached) return cached;

  const inFlight = chunksInFlight.get(bookId);
  if (inFlight) return inFlight;

  const promise = (async () => {
    const query = bookId ? `?book_id=${encodeURIComponent(bookId)}` : "";
    const response = await fetch(`${engineUrl()}/chunks${query}`, { signal });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(data?.error || `engine returned ${response.status}`);
    }
    const data: ChunksPayload = await response.json();
    chunksCache.set(bookId, data);
    return data;
  })();

  chunksInFlight.set(bookId, promise);
  try {
    return await promise;
  } finally {
    chunksInFlight.delete(bookId);
  }
}

export async function importEpubBook(
  filename: string,
  dataBase64: string
): Promise<{ ok: boolean; book_id: string; book?: BookCatalogItem; books?: BookCatalogItem[]; error?: string }> {
  const response = await fetch(`${engineUrl()}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "import", filename, data_base64: dataBase64 }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.error || `import failed with ${response.status}`);
  }
  return response.json();
}

export type AskRequest = {
  mode: string;
  book_id?: string;
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
