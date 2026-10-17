"use client";

import { forwardRef, useState, useRef, type CSSProperties } from "react";
import AnswerView from "@/components/AnswerView";
import { formatChapter } from "@/lib/anchor";
import { useAsk, type GlossItem } from "@/lib/store";

export type MarginCardProps = {
  gloss: GlossItem;
  top: number;
  placed: boolean;
  mini: boolean;
  active: boolean;
  hovered: boolean;
  onSelect: () => void;
  onHover: (hovered: boolean) => void;
  onHeightChange?: () => void;
};

function modeBadge(gloss: GlossItem): string {
  if (gloss.kind === "quiz") return "Quiz";
  const firstTurn = gloss.turns[0];
  const mode = firstTurn?.mode ?? (gloss as unknown as { mode?: string }).mode;
  if (mode === "explain") return "Explain";
  if (mode === "ask") return "Ask";
  if (mode === "quiz") return "Quiz";
  return "Answer";
}

function getDynamicFollowUps(gloss: GlossItem): string[] {
  const latestTurn = gloss.turns[gloss.turns.length - 1];
  if (latestTurn?.body?.followups && latestTurn.body.followups.length > 0) {
    return latestTurn.body.followups;
  }

  if (gloss.kind === "quiz") {
    return [
      "Why is this the key concept?",
      "Explain this in simpler words",
      "Give a practical example",
    ];
  }

  // Combine available text to extract key concepts
  const corpus = [
    gloss.heading || "",
    gloss.quote || "",
    latestTurn?.body?.answer?.slice(0, 300) || "",
  ].join(" ");

  const commonStops = new Set([
    "the", "a", "an", "in", "on", "at", "for", "to", "of", "and", "or", "is",
    "are", "was", "were", "what", "how", "why", "when", "this", "that", "it",
    "with", "as", "by", "from", "chapter", "figure", "table", "data", "book"
  ]);

  const matches = corpus.match(/\b[A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*)*\b|\b[A-Z]{2,}\b/g) || [];
  const candidates: string[] = [];
  const seen = new Set<string>();

  for (const m of matches) {
    const clean = m.trim();
    const lower = clean.toLowerCase();
    if (clean.length < 3) continue;
    if (commonStops.has(lower)) continue;
    if (!seen.has(lower)) {
      seen.add(lower);
      candidates.push(clean);
    }
    if (candidates.length >= 3) break;
  }

  if (candidates.length >= 2) {
    return [
      `How does this apply to ${candidates[0]}?`,
      `What are the trade-offs of ${candidates[1]}?`,
      "Explain with a concrete example",
    ];
  }
  if (candidates.length === 1) {
    return [
      `Why is ${candidates[0]} important here?`,
      "What are the main trade-offs?",
      "Explain with a real-world example",
    ];
  }

  return [
    "Why does this matter in practice?",
    "What are the core trade-offs?",
    "Explain with a real-world example",
  ];
}

function renderAnimatedTokens(text: string) {
  const parts = text.split(/(\s+)/);
  return parts.map((part, i) => (
    <span key={i} className="stream-token">
      {part}
    </span>
  ));
}

function renderStreamingText(raw: string) {
  let text = raw.replace(/^(?:read as|asked as):[^\n]*\n?/i, "");

  if (text.startsWith("[")) {
    const firstNewline = text.indexOf("\n");
    if (firstNewline !== -1) {
      const firstLine = text.slice(0, firstNewline).trim();
      const rest = text.slice(firstNewline + 1).trimStart();
      const quoteMatch = firstLine.match(
        /^\[(?:ch|chapter)\.?\s*([^\]]+)\]\s*"?([^"]*)"?$/i
      );

      if (quoteMatch) {
        const ch = quoteMatch[1].trim();
        const quoteText = quoteMatch[2].trim();
        return (
          <div className="turn-body is-streaming">
            <p className="answer">
              {renderAnimatedTokens(rest)}
              <span className="stream-cursor" aria-hidden="true" />
            </p>
            {quoteText ? (
              <p className="answer-quote">
                <span className="answer-quote-text">“{quoteText}”</span>
                <span className="chip">Ch. {formatChapter(ch)}</span>
              </p>
            ) : null}
          </div>
        );
      }
    } else {
      // Opening quote is still streaming
      const chMatch = text.match(
        /^\[(?:ch|chapter)\.?\s*([^\]]+)\]\s*"?([^"]*)$/i
      );
      if (chMatch) {
        const ch = chMatch[1].trim();
        const quotePreview = chMatch[2];
        return (
          <div className="streaming-quote-preview">
            <p className="answer-quote is-streaming">
              <span className="answer-quote-text">“{renderAnimatedTokens(quotePreview)}</span>
              <span className="stream-cursor" aria-hidden="true" />
              <span className="chip">Ch. {formatChapter(ch)}</span>
            </p>
          </div>
        );
      }
      return (
        <div className="streaming-quote-preview">
          <p className="answer">
            {renderAnimatedTokens(text)}
            <span className="stream-cursor" aria-hidden="true" />
          </p>
        </div>
      );
    }
  }

  return (
    <div className="turn-body is-streaming">
      <p className="answer">
        {renderAnimatedTokens(text)}
        <span className="stream-cursor" aria-hidden="true" />
      </p>
    </div>
  );
}

const MarginCard = forwardRef<HTMLElement, MarginCardProps>(function MarginCard(
  {
    gloss,
    top,
    placed,
    mini,
    active,
    hovered,
    onSelect,
    onHover,
    onHeightChange,
  },
  ref
) {
  const showCitation = useAsk((s) => s.showCitation);
  const removeGloss = useAsk((s) => s.removeGloss);
  const stopGloss = useAsk((s) => s.stopGloss);
  const toggleQuizKey = useAsk((s) => s.toggleQuizKey);
  const askFollowUp = useAsk((s) => s.askFollowUp);
  const startQuiz = useAsk((s) => s.startQuiz);
  const toggleMinimizeGloss = useAsk((s) => s.toggleMinimizeGloss);
  const setGlossDragOffset = useAsk((s) => s.setGlossDragOffset);
  const setGlossWidth = useAsk((s) => s.setGlossWidth);

  const [followUpText, setFollowUpText] = useState("");
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const isDraggingRef = useRef(false);
  const dragStartRef = useRef<{ clientX: number; clientY: number; origX: number; origY: number }>({
    clientX: 0,
    clientY: 0,
    origX: 0,
    origY: 0,
  });

  const isResizingRef = useRef(false);
  const resizeStartRef = useRef<{ clientX: number; startWidth: number }>({
    clientX: 0,
    startWidth: 320,
  });

  const badge = modeBadge(gloss);
  const chLabel = formatChapter(gloss.chapter);
  const latestTurn = gloss.turns[gloss.turns.length - 1];
  const canFollowUp =
    latestTurn &&
    (latestTurn.status === "done" ||
      latestTurn.status === "refused" ||
      latestTurn.status === "stopped");

  const copyAnswer = async () => {
    const parts: string[] = [];
    if (gloss.quote) {
      parts.push(`“${gloss.quote}” (${chLabel})`);
    }
    for (const t of gloss.turns) {
      if (t.question && t.question !== gloss.quote) {
        parts.push(`Q: ${t.question}`);
      }
      if (t.body?.answer) {
        parts.push(t.body.answer);
      } else if (t.streamText) {
        parts.push(t.streamText);
      }
    }
    const text = parts.join("\n\n");
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      // ignore clipboard failure
    }
  };

  const isMinimized = mini || Boolean(gloss.minimized);
  const dragX = gloss.dragOffset?.x ?? 0;
  const dragY = gloss.dragOffset?.y ?? 0;

  const style: CSSProperties = {
    transform:
      dragX !== 0 || dragY !== 0
        ? `translate3d(${dragX}px, ${Math.round(top + dragY)}px, 0)`
        : `translateY(${Math.round(top)}px)`,
    ...(placed ? null : { transition: "none" }),
    ...(gloss.customWidth
      ? {
          width: `${gloss.customWidth}px`,
          left: "auto",
          right: 0,
        }
      : null),
  };

  const handleHeaderPointerDown = (e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button, a, input")) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    isDraggingRef.current = true;
    dragStartRef.current = {
      clientX: e.clientX,
      clientY: e.clientY,
      origX: gloss.dragOffset?.x ?? 0,
      origY: gloss.dragOffset?.y ?? 0,
    };
  };

  const handleHeaderPointerMove = (e: React.PointerEvent<HTMLElement>) => {
    if (!isDraggingRef.current) return;
    const dx = e.clientX - dragStartRef.current.clientX;
    const dy = e.clientY - dragStartRef.current.clientY;
    setGlossDragOffset(gloss.id, {
      x: Math.round(dragStartRef.current.origX + dx),
      y: Math.round(dragStartRef.current.origY + dy),
    });
  };

  const handleHeaderPointerUp = (e: React.PointerEvent<HTMLElement>) => {
    if (!isDraggingRef.current) return;
    isDraggingRef.current = false;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      // ignore
    }
  };

  const handleResizePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    isResizingRef.current = true;
    resizeStartRef.current = {
      clientX: e.clientX,
      startWidth: gloss.customWidth ?? 320,
    };
  };

  const handleResizePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isResizingRef.current) return;
    const delta = resizeStartRef.current.clientX - e.clientX;
    const nextWidth = Math.max(280, Math.min(520, Math.round(resizeStartRef.current.startWidth + delta)));
    setGlossWidth(gloss.id, nextWidth);
    onHeightChange?.();
  };

  const handleResizePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isResizingRef.current) return;
    isResizingRef.current = false;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      // ignore
    }
    onHeightChange?.();
  };

  // Minimized 26px margin node indicator view
  if (isMinimized) {
    const snippet =
      (gloss.turns[0]?.question && gloss.turns[0].question !== gloss.quote
        ? gloss.turns[0].question
        : "") ||
      (gloss.quote ? `“${gloss.quote}”` : chLabel);

    return (
      <article
        ref={ref}
        role="button"
        tabIndex={0}
        data-gloss-id={gloss.id}
        aria-label={`${badge}: ${snippet}`}
        className={`gloss-node-indicator ${placed ? "" : "unplaced"} ${
          hovered ? "is-hover" : ""
        }`}
        style={style}
        onClick={() => {
          if (gloss.minimized) {
            toggleMinimizeGloss(gloss.id);
          }
          onSelect();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            if (gloss.minimized) {
              toggleMinimizeGloss(gloss.id);
            }
            onSelect();
          }
        }}
        onMouseEnter={() => onHover(true)}
        onMouseLeave={() => onHover(false)}
      >
        <span className="gloss-node-dot" aria-hidden="true" />
        <span className="gloss-node-badge">{badge}</span>
        <span className="gloss-node-title">{snippet}</span>
        <span className="gloss-node-expand" aria-hidden="true">+</span>
      </article>
    );
  }

  // Expanded card view
  return (
    <article
      ref={ref}
      data-gloss-id={gloss.id}
      aria-label={`${badge} note for ${chLabel}`}
      className={`gloss-card ${placed ? "" : "unplaced"} ${
        active ? "is-active" : ""
      } ${hovered ? "is-hover" : ""}`}
      style={style}
      onClick={onSelect}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
    >
      {/* Left resize handle */}
      <div
        className="gloss-resize-handle"
        onPointerDown={handleResizePointerDown}
        onPointerMove={handleResizePointerMove}
        onPointerUp={handleResizePointerUp}
        title="Drag left edge to resize card width"
        aria-hidden="true"
      />

      {/* Header row - draggable */}
      <header
        className="gloss-card-header"
        onPointerDown={handleHeaderPointerDown}
        onPointerMove={handleHeaderPointerMove}
        onPointerUp={handleHeaderPointerUp}
        onDoubleClick={(e) => {
          e.stopPropagation();
          setGlossDragOffset(gloss.id, { x: 0, y: 0 });
        }}
        title="Drag header to move card · Double-click to reset position"
      >
        <div className="gloss-card-title">
          <span className="mini-badge">{badge}</span>
          <span className="meta">·</span>
          <span className="meta">
            {gloss.kind === "whole"
              ? `Whole book · ${chLabel}`
              : chLabel}
          </span>
        </div>

        <div className="gloss-card-actions">
          {/* Width expand/compact toggle */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setGlossWidth(gloss.id, (gloss.customWidth ?? 320) >= 420 ? 320 : 440);
              onHeightChange?.();
            }}
            aria-label="Toggle wide card"
            title={(gloss.customWidth ?? 320) >= 420 ? "Compact width" : "Expand width"}
            className="gloss-icon-btn"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <polyline points="15 3 21 3 21 9" />
              <polyline points="9 21 3 21 3 15" />
              <line x1="21" y1="3" x2="14" y2="10" />
              <line x1="3" y1="21" x2="10" y2="14" />
            </svg>
          </button>

          {/* Minimize to node */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              toggleMinimizeGloss(gloss.id);
            }}
            aria-label="Minimize note"
            title="Minimize to margin node"
            className="gloss-icon-btn"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>

          {/* Copy answer */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              copyAnswer();
            }}
            aria-label={copied ? "Copied" : "Copy answer"}
            title={copied ? "Copied" : "Copy answer with citations"}
            className="gloss-icon-btn"
          >
            {copied ? (
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                className="gloss-icon-good"
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            ) : (
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
            )}
          </button>

          {/* Delete note */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              removeGloss(gloss.id);
            }}
            aria-label="Delete note"
            title="Delete note"
            className="gloss-icon-btn"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </header>

      {/* Sleek single-line passage ref bar */}
      {gloss.quote && gloss.kind !== "quiz" ? (
        <div
          className="card-passage-ref"
          role="button"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            const topCite = latestTurn?.body?.citations?.[0];
            showCitation({
              chunk_id: topCite?.chunk_id || gloss.chunkId,
              chapter: topCite?.chapter ? String(topCite.chapter) : gloss.chapter,
              quote: topCite?.quote || gloss.quote,
              at: topCite ? undefined : gloss.at,
              nonce: Date.now(),
            });
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              e.stopPropagation();
              const topCite = latestTurn?.body?.citations?.[0];
              showCitation({
                chunk_id: topCite?.chunk_id || gloss.chunkId,
                chapter: topCite?.chapter ? String(topCite.chapter) : gloss.chapter,
                quote: topCite?.quote || gloss.quote,
                at: topCite ? undefined : gloss.at,
                nonce: Date.now(),
              });
            }
          }}
          title="Jump to this passage in the book"
        >
          <span className="card-passage-quote">“{gloss.quote}”</span>
          <span className="card-passage-jump">Jump</span>
        </div>
      ) : null}

      {/* Turns */}
      <div className="gloss-turns">
        {gloss.turns.map((turn, idx) => (
          <div key={turn.id || idx} className="turn-container">
            {/* Subsequent turn separator */}
            {idx > 0 && (
              <div className="turn-divider">
                <span className="turn-badge">Follow-up</span>
              </div>
            )}

            {/* Turn question (for follow-ups or ask queries) */}
            {turn.question &&
              turn.question !== gloss.quote &&
              !(turn.mode === "quiz" && turn.question === "Quiz") && (
                <p className="turn-question">
                  {turn.question}
                </p>
              )}

            {/* Loading / Streaming state */}
            {(turn.status === "loading" || turn.status === "streaming") && (
              <div className="turn-busy">
                {turn.resetting && (
                  <p className="meta">
                    Re-checking the quote…
                  </p>
                )}
                {turn.streamText ? (
                  renderStreamingText(turn.streamText)
                ) : (
                  <div className="shimmer-wash">
                    <div className="shimmer" />
                    <div className="shimmer" />
                  </div>
                )}
                <div className="turn-status-row">
                  <span>
                    {(turn.elapsed ?? 0).toFixed(0)}s elapsed
                    {turn.elapsed && turn.elapsed > 8
                      ? " (~25s first-load model warmup)"
                      : ""}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      stopGloss(gloss.id);
                    }}
                    className="turn-stop-btn"
                  >
                    Stop
                  </button>
                </div>
              </div>
            )}

            {/* Completed / Refused state */}
            {turn.mode === "quiz" && turn.body && (
              <div className="quiz-turn">
                <p className="answer quiz-question">
                  {turn.body.answer}
                </p>
                <div className="quiz-reveal">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleQuizKey(gloss.id, turn.id);
                    }}
                    className="quiz-toggle"
                  >
                    {turn.showQuizKey ? "Hide the key" : "Show the key"}
                  </button>
                  {turn.showQuizKey && (
                    <div
                      className="quiz-key"
                      role={turn.body.citations[0] ? "button" : undefined}
                      tabIndex={turn.body.citations[0] ? 0 : undefined}
                      onClick={(e) => {
                        if (turn.body?.citations?.[0]) {
                          e.stopPropagation();
                          showCitation({
                            chunk_id: turn.body.citations[0].chunk_id,
                            chapter: turn.body.citations[0].chapter,
                            quote: turn.body.citations[0].quote,
                            nonce: Date.now(),
                          });
                        }
                      }}
                      onKeyDown={(e) => {
                        if (
                          (e.key === "Enter" || e.key === " ") &&
                          turn.body?.citations?.[0]
                        ) {
                          e.preventDefault();
                          e.stopPropagation();
                          showCitation({
                            chunk_id: turn.body.citations[0].chunk_id,
                            chapter: turn.body.citations[0].chapter,
                            quote: turn.body.citations[0].quote,
                            nonce: Date.now(),
                          });
                        }
                      }}
                      title={
                        turn.body.citations[0]
                          ? "Jump to this citation in the book"
                          : undefined
                      }
                    >
                      {turn.body.citations[0]?.quote ? (
                        <p className="answer-quote-text">
                          “{turn.body.citations[0].quote}”
                        </p>
                      ) : null}
                      {turn.body.citations[0] ? (
                        <span className="chip">
                          Ch. {turn.body.citations[0].chapter}
                        </span>
                      ) : null}
                    </div>
                  )}
                </div>
              </div>
            )}

            {turn.mode !== "quiz" && turn.body && (
              <div className="turn-body">
                <AnswerView
                  body={turn.body}
                  anchorQuote={gloss.quote}
                  onChip={showCitation}
                />
              </div>
            )}

            {/* Error state */}
            {turn.status === "error" && (
              <p className="turn-error">
                {turn.error || "Engine error occurred."}
              </p>
            )}

            {/* Stopped state */}
            {turn.status === "stopped" && (
              <p className="turn-stopped">
                Stopped — this is a partial answer.
              </p>
            )}
          </div>
        ))}
      </div>

      {/* Follow-up suggestions */}
      {canFollowUp && active && (
        <div className="followup-chips" role="group" aria-label="Suggested follow-ups">
          {gloss.kind === "quiz" && latestTurn?.status === "done" ? (
            <>
              <button
                type="button"
                className="followup-chip"
                onClick={(e) => {
                  e.stopPropagation();
                  startQuiz(gloss.chunkId, gloss.chapter);
                }}
              >
                Another quiz question
              </button>
              <button
                type="button"
                className="followup-chip"
                onClick={(e) => {
                  e.stopPropagation();
                  if (!latestTurn.showQuizKey) {
                    toggleQuizKey(gloss.id, latestTurn.id);
                  }
                  askFollowUp(gloss.id, "Explain why this is the answer in simpler words");
                }}
              >
                Explain the answer
              </button>
            </>
          ) : (
            getDynamicFollowUps(gloss).map((chipText) => (
              <button
                key={chipText}
                type="button"
                className="followup-chip"
                onClick={(e) => {
                  e.stopPropagation();
                  askFollowUp(gloss.id, chipText);
                }}
              >
                {chipText}
              </button>
            ))
          )}
        </div>
      )}

      {/* Follow-up input at bottom */}
      {canFollowUp && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const q = followUpText.trim();
            if (!q) return;
            askFollowUp(gloss.id, q);
            setFollowUpText("");
          }}
          onClick={(e) => e.stopPropagation()}
          className="followup-form"
        >
          <input
            ref={inputRef}
            value={followUpText}
            onChange={(e) => setFollowUpText(e.target.value)}
            placeholder="Ask a follow-up…"
            aria-label="Ask a follow-up"
            className="followup-input"
          />
          <button
            type="submit"
            disabled={!followUpText.trim()}
            aria-label="Send follow-up"
            className="followup-submit"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <line x1="12" y1="19" x2="12" y2="5" />
              <polyline points="5 12 12 5 19 12" />
            </svg>
          </button>
        </form>
      )}
    </article>
  );
});

export default MarginCard;
