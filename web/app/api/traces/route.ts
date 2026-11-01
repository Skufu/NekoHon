import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { DatabaseSync } from "node:sqlite";

// Next statically parses this value, so it must stay a literal. `output:
// export` cannot run a handler per request, which is why this route is a build
// time snapshot: the traces page is a development inspector, not a live feed.
export const dynamic = "force-static";

function findRepoRoot(): string {
  let curr = process.cwd();
  for (let i = 0; i < 4; i++) {
    if (
      fs.existsSync(path.join(curr, "artifacts", "runs", "traces.jsonl")) ||
      fs.existsSync(path.join(curr, "data", "books.json"))
    ) {
      return curr;
    }
    curr = path.resolve(curr, "..");
  }
  return process.cwd();
}

interface ChunkData {
  chunk_id: string;
  chapter?: string;
  heading?: string;
  text?: string;
}

const bookIndexCache = new Map<string, Map<string, ChunkData>>();

function loadBookChunkMap(repoRoot: string, bookId: string): Map<string, ChunkData> {
  if (bookIndexCache.has(bookId)) {
    return bookIndexCache.get(bookId)!;
  }
  const chunkMap = new Map<string, ChunkData>();
  try {
    const booksJsonPath = path.join(repoRoot, "data", "books.json");
    if (fs.existsSync(booksJsonPath)) {
      const books = JSON.parse(fs.readFileSync(booksJsonPath, "utf-8"));
      const book = Array.isArray(books)
        ? books.find((b: { book_id: string }) => b.book_id === bookId)
        : null;
      let indexPath = book?.index_path ? path.join(repoRoot, book.index_path) : null;
      if (!indexPath || !fs.existsSync(indexPath)) {
        if (bookId === "fde") indexPath = path.join(repoRoot, "data", "index.sqlite");
        else if (bookId === "quantization") indexPath = path.join(repoRoot, "data", "index.quantization.sqlite");
        else if (bookId === "ddia") indexPath = path.join(repoRoot, "data", "index.ddia.sqlite");
      }
      if (indexPath && fs.existsSync(indexPath)) {
        const db = new DatabaseSync(indexPath, { readOnly: true });
        try {
          const rows = db
            .prepare("SELECT chunk_id, chapter, heading, text FROM chunks")
            .all() as Array<{
              chunk_id?: string | null;
              chapter?: string | number | null;
              heading?: string | null;
              text?: string | null;
            }>;
          for (const row of rows) {
            if (row.chunk_id) {
              chunkMap.set(row.chunk_id, {
                chunk_id: row.chunk_id,
                chapter:
                  row.chapter === null || row.chapter === undefined
                    ? undefined
                    : String(row.chapter),
                heading: row.heading || "",
                text: row.text || "",
              });
            }
          }
        } finally {
          db.close();
        }
      }
    }
  } catch {
    // Return empty map on read error
  }
  bookIndexCache.set(bookId, chunkMap);
  return chunkMap;
}

type TraceRecord = Record<string, any>;

function classifyTrace(t: TraceRecord): { is_issue: boolean; issue_tags: string[] } {
  const tags: string[] = [];
  const status = t.status as string | undefined;
  const error = t.error as string | null | undefined;
  if (status !== "ok" || Boolean(error)) {
    tags.push("Error");
  }

  const query = t.query as { guard_blocked?: string | null } | undefined;
  if (query?.guard_blocked) {
    tags.push("Guard blocked");
  }

  const outcome = t.outcome as { transforms?: string[]; final_refused?: boolean } | undefined;
  const transforms = Array.isArray(outcome?.transforms) ? outcome.transforms : [];
  if (transforms.includes("retry_uncited")) {
    tags.push("Uncited retry");
  }

  const llm = t.llm as { calls?: Array<{ raw_refused?: boolean }>; vram_load_ms?: number; ttft_ms?: number } | undefined;
  if (outcome?.final_refused || llm?.calls?.some((c) => c.raw_refused)) {
    tags.push("Refusal");
  }

  const traceVram = typeof t.vram_load_ms === "number" ? t.vram_load_ms : 0;
  const llmVram = typeof llm?.vram_load_ms === "number" ? llm.vram_load_ms : 0;
  if (traceVram >= 100 || llmVram >= 100) {
    tags.push("VRAM stall");
  }

  if (typeof llm?.ttft_ms === "number" && llm.ttft_ms >= 1500) {
    tags.push("Slow TTFT");
  }

  const anomalies = Array.isArray(t.anomalies) ? (t.anomalies as string[]) : [];
  for (const a of anomalies) {
    if (a === "vram_cold_load" && !tags.includes("VRAM stall")) tags.push("VRAM stall");
    if (a === "slow_ttft" && !tags.includes("Slow TTFT")) tags.push("Slow TTFT");
  }

  // A cold model load is the normal case (the model unloads after idle), so a
  // load-only trace is not flagged; it still carries the tag for the count.
  const loadOnly = tags.length > 0 && tags.every((tag) => tag === "VRAM stall");

  return {
    is_issue: tags.length > 0 && !loadOnly,
    issue_tags: tags,
  };
}

function reconstructTrace(t: TraceRecord, repoRoot: string): TraceRecord {
  if (!t || typeof t !== "object") return t;
  const copy = JSON.parse(JSON.stringify(t)) as TraceRecord;
  const bookId = (copy.book_id as string) || "fde";
  const chunkMap = loadBookChunkMap(repoRoot, bookId);

  const retrieval = copy.retrieval as { shown_passages?: Array<Record<string, unknown>> } | undefined;
  if (retrieval && Array.isArray(retrieval.shown_passages)) {
    for (const p of retrieval.shown_passages) {
      const cid = p.chunk_id as string | undefined;
      if (cid) {
        const match = chunkMap.get(cid);
        if (match) {
          p.heading = match.heading || "";
          p.text = match.text || "";
          p.text_preview = match.text ? match.text.slice(0, 320) : "";
        }
      }
    }
  }

  const outcome = copy.outcome as { cited_chunks?: Array<string | { chunk_id: string }>; cited_chunks_reconstructed?: unknown[] } | undefined;
  if (outcome && Array.isArray(outcome.cited_chunks)) {
    const citedReconstructed: Array<Record<string, unknown>> = [];
    for (const c of outcome.cited_chunks) {
      const cid = typeof c === "string" ? c : c?.chunk_id;
      if (cid) {
        const match = chunkMap.get(cid);
        if (match) {
          citedReconstructed.push({
            chunk_id: cid,
            chapter: match.chapter,
            heading: match.heading || "",
            text_preview: match.text ? match.text.slice(0, 320) : "",
          });
        } else {
          citedReconstructed.push({ chunk_id: cid });
        }
      }
    }
    outcome.cited_chunks_reconstructed = citedReconstructed;
  }

  return copy;
}

export async function GET() {
  const repoRoot = findRepoRoot();
  const tracesPath = path.join(repoRoot, "artifacts", "runs", "traces.jsonl");

  if (!fs.existsSync(tracesPath)) {
    return NextResponse.json({
      summary: {
        total_traces: 0,
        issues_count: 0,
        median_latency_ms: 0,
        avg_tok_per_sec: 0,
        vram_stalls_count: 0,
      },
      traces: [],
      selected_trace: null,
      catalog: [],
    });
  }

  const lines = fs
    .readFileSync(tracesPath, "utf-8")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  const rawTraces: TraceRecord[] = [];
  for (const line of lines) {
    try {
      const parsed = JSON.parse(line);
      if (parsed && typeof parsed === "object") {
        rawTraces.push(parsed);
      }
    } catch {
      // Ignore unparseable line
    }
  }

  // Reverse so newest traces come first
  rawTraces.reverse();

  // Load books catalog
  let catalog: Array<{ book_id: string; title: string }> = [];
  try {
    const booksJsonPath = path.join(repoRoot, "data", "books.json");
    if (fs.existsSync(booksJsonPath)) {
      const bList = JSON.parse(fs.readFileSync(booksJsonPath, "utf-8"));
      if (Array.isArray(bList)) {
        catalog = bList.map((b: { book_id: string; title: string }) => ({
          book_id: b.book_id,
          title: b.title,
        }));
      }
    }
  } catch {
    catalog = [];
  }

  let totalIssues = 0;
  let totalVramStalls = 0;
  const latencies: number[] = [];
  const tokRates: number[] = [];

  // Return all traces and let the client filter for instant zero-latency UI
  const decorated = rawTraces.map((t) => {
    const classification = classifyTrace(t);
    if (classification.is_issue) totalIssues += 1;
    if (classification.issue_tags.includes("VRAM stall")) totalVramStalls += 1;

    const totalMs = typeof t.total_ms === "number" ? t.total_ms : 0;
    if (totalMs > 0) latencies.push(totalMs);

    const llm = t.llm as { tok_per_sec?: number } | undefined;
    if (typeof llm?.tok_per_sec === "number" && llm.tok_per_sec > 0) {
      tokRates.push(llm.tok_per_sec);
    }

    return {
      ...reconstructTrace(t, repoRoot),
      is_issue: classification.is_issue,
      issue_tags: classification.issue_tags,
    };
  });

  latencies.sort((a, b) => a - b);
  const medianLatency =
    latencies.length > 0 ? latencies[Math.floor(latencies.length / 2)] : 0;
  const avgTokPerSec =
    tokRates.length > 0
      ? tokRates.reduce((sum, v) => sum + v, 0) / tokRates.length
      : 0;

  return NextResponse.json({
    summary: {
      total_traces: rawTraces.length,
      issues_count: totalIssues,
      median_latency_ms: Math.round(medianLatency),
      avg_tok_per_sec: Math.round(avgTokPerSec * 10) / 10,
      vram_stalls_count: totalVramStalls,
    },
    traces: decorated,
    catalog,
  });
}
