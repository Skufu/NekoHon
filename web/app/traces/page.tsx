"use client";

import { useEffect, useState, useCallback, useRef, type KeyboardEvent } from "react";
import Link from "next/link";
import "./traces.css";

interface TraceSummary {
  total_traces: number;
  issues_count: number;
  median_latency_ms: number;
  avg_tok_per_sec: number;
  vram_stalls_count: number;
}

interface PassageItem {
  rank: number;
  chunk_id: string;
  chapter: string;
  score: number;
  phrase_score?: number;
  heading?: string;
  text?: string;
  text_preview?: string;
}

interface TraceData {
  trace_id: string;
  timestamp: string;
  mode: string;
  book_id: string;
  model: string;
  total_ms: number;
  is_issue?: boolean;
  issue_tags?: string[];
  vram_load_ms?: number;
  query?: {
    raw?: string;
    resolved?: string;
    asked?: string;
    pin_chunk?: string | null;
    guard_blocked?: string | null;
  };
  retrieval?: {
    retrieval_ms?: number;
    shown_passages?: PassageItem[];
  };
  llm?: {
    llm_ms?: number;
    ttft_ms?: number | null;
    vram_load_ms?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    tok_per_sec?: number;
  };
  outcome?: {
    transforms?: string[];
    final_refused?: boolean;
    cited_chunks?: string[];
    answer_preview?: string;
  };
}

interface CatalogBook {
  book_id: string;
  title: string;
}

type StatusKind = "blocked" | "refused" | "slow" | "cold" | "retried" | "answered" | "retrieve";

// A warm answer on this machine lands in 0.4-1.2s (measured, AGENTS.md), so
// past 3s something genuinely stalled. The one-time model load is subtracted
// first: a cold start is normal and must not read as a slow answer.
const SLOW_ANSWER_MS = 3000;

function friendlyBookTitle(bookId: string, catalog: CatalogBook[]): string {
  const found = catalog.find((b) => b.book_id === bookId);
  if (!found || !found.title) return bookId;
  if (found.title.length > 26) return `${found.title.slice(0, 24)}...`;
  return found.title;
}

function formatTime(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    });
  } catch {
    return isoStr.slice(11, 19);
  }
}

function formatSeconds(ms: number): string {
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(1)}s`;
  }
  return `${Math.round(ms)}ms`;
}

function coldLoadMs(t: TraceData): number {
  return Math.max(t.vram_load_ms || 0, t.llm?.vram_load_ms || 0);
}

function getStatusDetails(t: TraceData): {
  label: string;
  badgeClass: string;
  kind: StatusKind;
} {
  // A retrieval request looks up passages and never asks the model for an
  // answer, so it must not be reported as an answer that went missing.
  if (t.mode === "retrieve") {
    return { label: "Passages only", badgeClass: "traces-status-neutral", kind: "retrieve" };
  }
  if (t.query?.guard_blocked) {
    return { label: "Blocked", badgeClass: "traces-status-danger", kind: "blocked" };
  }
  if (t.outcome?.final_refused) {
    return { label: "Refused", badgeClass: "traces-status-neutral", kind: "refused" };
  }
  const coldMs = coldLoadMs(t);
  const answerMs = (t.total_ms || 0) - coldMs;
  if (answerMs >= SLOW_ANSWER_MS) {
    return {
      label: `Slow · ${formatSeconds(t.total_ms)}`,
      badgeClass: "traces-status-warning",
      kind: "slow",
    };
  }
  if (coldMs >= 100) {
    return {
      label: `Cold start · ${formatSeconds(coldMs)}`,
      badgeClass: "traces-status-neutral",
      kind: "cold",
    };
  }
  if (t.outcome?.transforms?.includes("retry_uncited")) {
    return { label: "Retried", badgeClass: "traces-status-warning", kind: "retried" };
  }
  return { label: "Answered", badgeClass: "traces-status-good", kind: "answered" };
}

function getVerdict(t: TraceData): { text: string; tone: string } {
  if (t.mode === "retrieve") {
    return {
      text: "Passages looked up; no answer was requested",
      tone: "traces-tone-neutral",
    };
  }
  if (t.query?.guard_blocked) {
    return { text: `Blocked: ${t.query.guard_blocked}`, tone: "traces-tone-danger" };
  }
  if (t.outcome?.final_refused) {
    return { text: "Refused: this book does not cover it", tone: "traces-tone-neutral" };
  }
  const coldMs = coldLoadMs(t);
  if (coldMs >= 100) {
    return {
      text: `Answered, after a ${formatSeconds(coldMs)} pause to load the model`,
      tone: "traces-tone-neutral",
    };
  }
  if (t.outcome?.transforms?.includes("retry_uncited")) {
    return { text: "Answered on a second try", tone: "traces-tone-warning" };
  }
  return { text: "Answered", tone: "traces-tone-good" };
}

export default function TracesPage() {
  const [summary, setSummary] = useState<TraceSummary>({
    total_traces: 0,
    issues_count: 0,
    median_latency_ms: 0,
    avg_tok_per_sec: 0,
    vram_stalls_count: 0,
  });
  const [allTraces, setAllTraces] = useState<TraceData[]>([]);
  const [selectedTrace, setSelectedTrace] = useState<TraceData | null>(null);
  const [catalog, setCatalog] = useState<CatalogBook[]>([]);

  const [activeTab, setActiveTab] = useState<"passages" | "perf">("passages");
  const [bookFilter, setBookFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [expandedPassage, setExpandedPassage] = useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState<boolean>(false);

  const selectedIdRef = useRef<string | null>(null);
  selectedIdRef.current = selectedTrace?.trace_id || null;

  const fetchTraces = useCallback(async () => {
    try {
      const res = await fetch("/api/traces", { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();

      setSummary(data.summary);
      setAllTraces(data.traces || []);
      setCatalog(data.catalog || []);

      if (data.traces && data.traces.length > 0) {
        if (selectedIdRef.current) {
          const match = data.traces.find(
            (t: TraceData) => t.trace_id === selectedIdRef.current
          );
          if (match) {
            setSelectedTrace(match);
          } else {
            setSelectedTrace(data.traces[0]);
          }
        } else {
          setSelectedTrace(data.traces[0]);
        }
      }
    } catch {
      // Network or fetch error
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTraces();
  }, [fetchTraces]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      fetchTraces();
    }, 3000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchTraces]);

  // A passage opened on one question must not stay open on the next.
  const selectedId = selectedTrace?.trace_id || null;
  useEffect(() => {
    setExpandedPassage(null);
  }, [selectedId]);

  const filteredTraces = allTraces.filter((t) => {
    if (bookFilter && bookFilter !== "all" && t.book_id !== bookFilter) {
      return false;
    }
    const status = getStatusDetails(t);
    if (categoryFilter === "answered" && status.kind !== "answered") {
      return false;
    }
    if (categoryFilter === "refused" && status.kind !== "refused") {
      return false;
    }
    if (
      categoryFilter === "delayed" &&
      status.kind !== "cold" &&
      status.kind !== "slow"
    ) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      const raw = (t.query?.raw || "").toLowerCase();
      const resolved = (t.query?.resolved || "").toLowerCase();
      const bookName = friendlyBookTitle(t.book_id, catalog).toLowerCase();
      if (!raw.includes(q) && !resolved.includes(q) && !bookName.includes(q)) {
        return false;
      }
    }
    return true;
  });

  const handleSelectTrace = (trace: TraceData) => {
    setSelectedTrace(trace);
    setMobileDetailOpen(true);
  };

  const moveSelection = (step: 1 | -1) => {
    if (filteredTraces.length === 0) return;
    const current = selectedTrace?.trace_id;
    const index = filteredTraces.findIndex((t) => t.trace_id === current);
    const nextIndex =
      index === -1
        ? 0
        : Math.min(filteredTraces.length - 1, Math.max(0, index + step));
    const next = filteredTraces[nextIndex];
    if (next && next.trace_id !== current) {
      setSelectedTrace(next);
    }
  };

  const handleListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const tag = (event.target as HTMLElement).tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveSelection(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveSelection(-1);
    }
  };

  const stallMs = selectedTrace ? coldLoadMs(selectedTrace) : 0;

  // Timeline percentages
  const totalMs = selectedTrace?.total_ms || 1;
  const searchMs = selectedTrace?.retrieval?.retrieval_ms || 0;
  const searchPct = Math.min(100, Math.round((searchMs / totalMs) * 100));
  const stallPct = Math.min(100 - searchPct, Math.round((stallMs / totalMs) * 100));
  const llmPct = Math.max(0, 100 - searchPct - stallPct);

  const verdict = selectedTrace ? getVerdict(selectedTrace) : null;
  const coldMs = selectedTrace ? coldLoadMs(selectedTrace) : 0;

  return (
    <div className="traces-root">
      <div className="traces-container">
        {/* Header */}
        <header className="traces-header">
          <div className="traces-header-left">
            <h1 className="traces-title">Reading Companion History</h1>
            <p className="traces-subtitle">See how questions were answered from the books</p>
          </div>
          <div className="traces-header-right">
            <Link href="/" className="traces-nav-link">
              Back to Reader
            </Link>
            <button
              type="button"
              className={`traces-auto-btn ${autoRefresh ? "is-active" : ""}`}
              onClick={() => setAutoRefresh(!autoRefresh)}
              aria-pressed={autoRefresh}
            >
              {autoRefresh ? "Live: On" : "Live: Off"}
            </button>
            <button
              type="button"
              className="traces-refresh-btn"
              onClick={() => fetchTraces()}
            >
              Refresh
            </button>
          </div>
        </header>

        {/* Friendly Summary Cards */}
        <div className="traces-kpi-bar">
          <div className="traces-kpi-card">
            <span className="traces-kpi-label">Questions Asked</span>
            <span className="traces-kpi-value">{summary.total_traces}</span>
            <span className="traces-kpi-desc">Total questions kept</span>
          </div>
          <div className="traces-kpi-card">
            <span className="traces-kpi-label">Typical Time</span>
            <span className="traces-kpi-value">{formatSeconds(summary.median_latency_ms)}</span>
            <span className="traces-kpi-desc">
              Middle value: half were faster, half were slower
            </span>
          </div>
          <div className="traces-kpi-card">
            <span className="traces-kpi-label">Writing Speed</span>
            <span className="traces-kpi-value">
              {Math.round(summary.avg_tok_per_sec)} tokens/s
            </span>
            <span className="traces-kpi-desc">
              Tokens per second, measured by the local model
            </span>
          </div>
          <div className="traces-kpi-card">
            <span className="traces-kpi-label">Cold Starts</span>
            <span className="traces-kpi-value">{summary.vram_stalls_count}</span>
            <span className="traces-kpi-desc">Questions that waited for the model to load</span>
          </div>
          <div className="traces-kpi-card">
            <span className="traces-kpi-label">Flagged Questions</span>
            <span className="traces-kpi-value">{summary.issues_count}</span>
            <span className="traces-kpi-desc">Questions with a warning noted</span>
          </div>
        </div>

        {/* Toolbar */}
        <div className="traces-toolbar">
          <input
            type="text"
            className="traces-search-input"
            placeholder="Search questions or topics..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />

          <select
            className="traces-select"
            value={bookFilter}
            onChange={(e) => setBookFilter(e.target.value)}
            aria-label="Filter by book"
          >
            <option value="all">All Books</option>
            {catalog.map((b) => (
              <option key={b.book_id} value={b.book_id}>
                {friendlyBookTitle(b.book_id, catalog)}
              </option>
            ))}
          </select>

          <div className="traces-filter-tabs">
            <button
              type="button"
              className={`traces-filter-tab ${categoryFilter === "all" ? "is-active" : ""}`}
              onClick={() => setCategoryFilter("all")}
            >
              All
            </button>
            <button
              type="button"
              className={`traces-filter-tab ${categoryFilter === "answered" ? "is-active" : ""}`}
              onClick={() => setCategoryFilter("answered")}
            >
              Answered
            </button>
            <button
              type="button"
              className={`traces-filter-tab ${categoryFilter === "refused" ? "is-active" : ""}`}
              onClick={() => setCategoryFilter("refused")}
            >
              Refused
            </button>
            <button
              type="button"
              className={`traces-filter-tab ${categoryFilter === "delayed" ? "is-active" : ""}`}
              onClick={() => setCategoryFilter("delayed")}
            >
              Delayed
            </button>
          </div>
        </div>

        {/* Main Workspace */}
        <div className={`traces-workspace ${mobileDetailOpen ? "is-detail-open" : ""}`}>
          {/* Left: Questions List */}
          <aside className="traces-sidebar">
            <div className="traces-sidebar-header">
              <span className="traces-sidebar-count">
                {filteredTraces.length} {filteredTraces.length === 1 ? "question" : "questions"}
              </span>
            </div>
            <div className="traces-list" onKeyDown={handleListKeyDown}>
              {filteredTraces.length === 0 ? (
                <div className="traces-empty">
                  <h3 className="traces-empty-title">No questions found</h3>
                  <p className="traces-empty-desc">
                    {isLoading
                      ? "Loading reading history..."
                      : "Try choosing 'All' or searching for another keyword."}
                  </p>
                </div>
              ) : (
                filteredTraces.map((t) => {
                  const isSelected = selectedTrace?.trace_id === t.trace_id;
                  const status = getStatusDetails(t);
                  const bookName = friendlyBookTitle(t.book_id, catalog);
                  const queryText = t.query?.raw || t.query?.asked || "Question";
                  return (
                    <button
                      key={t.trace_id}
                      type="button"
                      className={`traces-item ${isSelected ? "is-selected" : ""}`}
                      aria-current={isSelected ? "true" : undefined}
                      onClick={() => handleSelectTrace(t)}
                    >
                      <div className="traces-item-top">
                        <span className="traces-item-time">{formatTime(t.timestamp)}</span>
                        <span className="traces-item-book">{bookName}</span>
                        <span className="traces-item-ms">{formatSeconds(t.total_ms)}</span>
                      </div>
                      <p className="traces-item-query">{queryText}</p>
                      <div className="traces-item-status-row">
                        <span className={`traces-status-badge ${status.badgeClass}`}>
                          {status.label}
                        </span>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </aside>

          {/* Right: Friendly Reading Inspector */}
          <main className="traces-detail">
            <button
              type="button"
              className="traces-back-btn"
              onClick={() => setMobileDetailOpen(false)}
            >
              Back to questions
            </button>

            {selectedTrace ? (
              <>
                {/* One header: status line, then the question, then metadata once */}
                <header className="traces-trace-head">
                  {verdict && (
                    <p className={`traces-verdict-line ${verdict.tone}`}>
                      <span className="traces-status-dot" />
                      {verdict.text}
                    </p>
                  )}
                  <h2 className="traces-trace-question">
                    {selectedTrace.query?.raw || selectedTrace.query?.asked || "Question"}
                  </h2>
                  {selectedTrace.query?.resolved &&
                    selectedTrace.query.resolved !== selectedTrace.query.raw && (
                      <p className="traces-qa-repair">
                        Understood as: &ldquo;{selectedTrace.query.resolved}&rdquo;
                      </p>
                    )}
                  <p className="traces-trace-meta">
                    {friendlyBookTitle(selectedTrace.book_id, catalog)} · Asked at{" "}
                    {formatTime(selectedTrace.timestamp)} · Took{" "}
                    {formatSeconds(selectedTrace.total_ms)}
                    {coldMs >= 100 ? ` (${formatSeconds(coldMs)} loading the model)` : ""}
                  </p>
                </header>

                <section className="traces-answer-card">
                  <span className="traces-qa-label">
                    {selectedTrace.mode === "retrieve" ? "Passages" : "Answer"}
                  </span>
                  <p className="traces-qa-answer">
                    {selectedTrace.mode === "retrieve"
                      ? `This request only looked up passages (${selectedTrace.retrieval?.shown_passages?.length || 0} shown). No answer was asked for.`
                      : selectedTrace.outcome?.answer_preview ||
                        (selectedTrace.outcome?.final_refused
                          ? "Not in this book."
                          : "No answer was recorded.")}
                  </p>

                  {selectedTrace.outcome?.cited_chunks &&
                    selectedTrace.outcome.cited_chunks.length > 0 && (
                      <div className="traces-qa-meta-row">
                        <span className="traces-qa-label">Source Citation:</span>
                        {selectedTrace.outcome.cited_chunks.map((cid) => (
                          <span key={cid} className="traces-citation-tag">
                            {cid}
                          </span>
                        ))}
                      </div>
                    )}
                </section>

                {/* Depth Tabs: Passages vs Performance */}
                <nav className="traces-tabs-nav" aria-label="Inspector tabs">
                  <button
                    type="button"
                    className={`traces-tab-btn ${activeTab === "passages" ? "is-active" : ""}`}
                    onClick={() => setActiveTab("passages")}
                  >
                    Book Passages Found ({selectedTrace.retrieval?.shown_passages?.length || 0})
                  </button>
                  <button
                    type="button"
                    className={`traces-tab-btn ${activeTab === "perf" ? "is-active" : ""}`}
                    onClick={() => setActiveTab("perf")}
                  >
                    Speed and Health
                  </button>
                </nav>

                <div className="traces-tab-content">
                  {activeTab === "passages" ? (
                    <div className="traces-passages-list">
                      {selectedTrace.retrieval?.shown_passages &&
                      selectedTrace.retrieval.shown_passages.length > 0 ? (
                        selectedTrace.retrieval.shown_passages.map((p) => {
                          const isExpanded = expandedPassage === p.chunk_id;
                          return (
                            <button
                              key={p.chunk_id}
                              type="button"
                              className={`traces-passage-card ${isExpanded ? "is-expanded" : ""}`}
                              aria-expanded={isExpanded}
                              onClick={() =>
                                setExpandedPassage(isExpanded ? null : p.chunk_id)
                              }
                            >
                              <span className="traces-passage-header">
                                <span className="traces-passage-ch">
                                  #{p.rank} · Chapter {p.chapter}
                                </span>
                                {typeof p.score === "number" && p.score > 0 && (
                                  <span
                                    className="traces-passage-score"
                                    title="Dense cosine similarity on unit vectors, not a percentage: unrelated text scores about 0.44 on this embedder, so the usable band is roughly 0.44-0.76. Rank comes from phrase and lexical boosts on top of the dense order, so a lower cosine can still rank higher."
                                  >
                                    cosine {p.score.toFixed(4)}
                                    {typeof p.phrase_score === "number" && p.phrase_score !== 0 && (
                                      <>
                                        {" · phrase "}
                                        {p.phrase_score > 0 ? "+" : ""}
                                        {p.phrase_score}
                                      </>
                                    )}
                                  </span>
                                )}
                              </span>
                              {p.heading && (
                                <span className="traces-passage-heading">{p.heading}</span>
                              )}
                              <span className="traces-passage-quote">
                                {(isExpanded ? p.text : p.text_preview) ||
                                  p.text ||
                                  "This passage was matched from the book index."}
                              </span>
                              <span className="traces-passage-hint">
                                {isExpanded ? "Show less" : "Read the full passage"}
                              </span>
                            </button>
                          );
                        })
                      ) : (
                        <div className="traces-empty">
                          <p className="traces-empty-desc">
                            No passages were retrieved for this question.
                          </p>
                        </div>
                      )}
                    </div>
                  ) : (
                    /* Performance & Health Tab */
                    <div className="traces-perf-card">
                      {/* Visual Timeline Bar */}
                      <span className="traces-qa-label">Time Breakdown</span>
                      <div
                        className="traces-timeline-bar"
                        role="progressbar"
                        aria-valuenow={100}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      >
                        <div
                          className="traces-timeline-segment traces-timeline-search"
                          style={{ width: `${searchPct}%` }}
                          title={`Search: ${formatSeconds(searchMs)}`}
                        />
                        {stallPct > 0 && (
                          <div
                            className="traces-timeline-segment traces-timeline-stall"
                            style={{ width: `${stallPct}%` }}
                            title={`Model loading: ${formatSeconds(stallMs)}`}
                          />
                        )}
                        <div
                          className="traces-timeline-segment traces-timeline-llm"
                          style={{ width: `${llmPct}%` }}
                          title={`Writing Answer: ${formatSeconds(selectedTrace.llm?.llm_ms || 0)}`}
                        />
                      </div>

                      <div className="traces-timeline-legend">
                        <div className="traces-legend-item">
                          <span className="traces-legend-dot traces-legend-dot-search" />
                          <span>Searching Book ({formatSeconds(searchMs)})</span>
                        </div>
                        {stallMs > 0 && (
                          <div className="traces-legend-item">
                            <span className="traces-legend-dot traces-legend-dot-stall" />
                            <span>Model Loading ({formatSeconds(stallMs)})</span>
                          </div>
                        )}
                        <div className="traces-legend-item">
                          <span className="traces-legend-dot traces-legend-dot-llm" />
                          <span>Writing Answer ({formatSeconds(selectedTrace.llm?.llm_ms || 0)})</span>
                        </div>
                      </div>

                      {/* Plain-English Metrics Grid */}
                      <div className="traces-perf-grid">
                        <div className="traces-perf-item">
                          <span className="traces-perf-label">Answer Generation Rate</span>
                          <span className="traces-perf-val">
                            {selectedTrace.llm?.tok_per_sec
                              ? `${selectedTrace.llm.tok_per_sec.toFixed(1)} tokens/sec`
                              : "N/A"}
                          </span>
                          <span className="traces-perf-note">
                            Speed of the offline model running on your computer
                          </span>
                        </div>

                        <div className="traces-perf-item">
                          <span className="traces-perf-label">First Word Reaction</span>
                          <span className="traces-perf-val">
                            {selectedTrace.llm?.ttft_ms
                              ? formatSeconds(selectedTrace.llm.ttft_ms)
                              : "Instant"}
                          </span>
                          <span className="traces-perf-note">
                            Delay before the model began typing out the answer
                          </span>
                        </div>

                        <div className="traces-perf-item">
                          <span className="traces-perf-label">Book Context Read</span>
                          <span className="traces-perf-val">
                            {selectedTrace.llm?.prompt_tokens || 0} tokens
                          </span>
                          <span className="traces-perf-note">
                            Amount of book text handed to the model, counted in tokens
                          </span>
                        </div>

                        <div className="traces-perf-item">
                          <span className="traces-perf-label">Model Running Locally</span>
                          <span className="traces-perf-val">
                            {selectedTrace.model}
                          </span>
                          <span className="traces-perf-note">
                            Local model running directly on localhost without cloud APIs
                          </span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="traces-empty">
                <h3 className="traces-empty-title">Select a question</h3>
                <p className="traces-empty-desc">
                  Choose any question from the list on the left to see the answer and where it came from in the book.
                </p>
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
