"use client";

import { useState, useMemo } from "react";
import { formatChapter } from "@/lib/anchor";
import { splitAnswer } from "@/lib/answer";
import { engineUrl, fetchPassages, type AnswerBody, type Citation, type PassageHit } from "@/lib/engine";
import { useAsk } from "@/lib/store";

function sameWords(a: string, b: string) {
  return (
    a.replace(/\s+/g, " ").trim().toLowerCase() ===
    b.replace(/\s+/g, " ").trim().toLowerCase()
  );
}

function chipLabel(citation: Citation, index: number, numbered: boolean) {
  const chapter = formatChapter(citation.chapter);
  return numbered ? `${index} \u00b7 ${chapter}` : chapter;
}

export type AskAnswerSplit = {
  quote?: string;
  chapter?: string;
  gloss: string;
  disclosure?: string;
};

export function splitAskAnswer(answer: string): AskAnswerSplit {
  let text = answer || "";
  let disclosure: string | undefined;

  // Capture the first Read as: "..." or Asked as: "..." on a single line
  const discMatch = text.match(/(?:^|\n)((?:Read as|Asked as):[^\n]+)/i);
  if (discMatch) {
    disclosure = discMatch[1].trim();
  }

  // Strip any trailing \nAsked as: ... or \nRead as: ... (even if multi-line)
  text = text.replace(/\n(?:Asked as|Read as):[\s\S]*$/i, "");

  const lines = text.split("\n").map((l) => l.trim());
  const firstLine = lines[0] || "";

  // Check if lines has a quote on line 1 ([Ch. N] "quote")
  const quoteMatch = firstLine.match(/^\[(?:ch|chapter)\.?\s*([^\]]+)\]\s*"?([^"]*)"?$/i);
  let quote: string | undefined;
  let chapter: string | undefined;
  let remainingLines = lines;

  if (quoteMatch) {
    chapter = quoteMatch[1].trim();
    quote = quoteMatch[2].trim();
    remainingLines = lines.slice(1);
  }

  // gloss is cleanly extracted from the remaining non-empty lines
  // (ignoring any line starting with Asked as: or Read as: or Technical solutions in style artifacts)
  const glossLines = remainingLines.filter((line) => {
    if (!line) return false;
    if (/^(?:asked as|read as):/i.test(line)) return false;
    if (/^technical solutions in\b/i.test(line)) return false;
    return true;
  });

  const gloss = glossLines.join("\n\n").trim();

  return {
    quote,
    chapter,
    gloss: gloss || (quote ? "" : firstLine),
    disclosure,
  };
}

export default function AnswerView({
  body,
  onChip,
  engine,
  selection = "",
  anchorQuote = "",
  question,
  onCopy,
  copied,
}: {
  body: AnswerBody;
  onChip?: (citation: Citation) => void;
  engine?: string;
  selection?: string;
  anchorQuote?: string;
  question?: string;
  onCopy?: () => void;
  copied?: boolean;
}) {
  const [hiddenFigures, setHiddenFigures] = useState<Record<string, boolean>>({});
  const [passagesOpen, setPassagesOpen] = useState(false);
  const [passages, setPassages] = useState<PassageHit[] | null>(null);
  const [passagesError, setPassagesError] = useState(false);
  const bookId = useAsk((s) => s.activeBookId);
  const storeShowCitation = useAsk((s) => s.showCitation);
  const handleChip = onChip ?? storeShowCitation;
  const activeEngine = engine ?? engineUrl();
  const activeQuote = anchorQuote || selection || "";

  const split = useMemo(() => splitAnswer(body), [body]);
  const numbered = body.citations.length > 1;
  const indexOf = (citation: Citation) => body.citations.indexOf(citation) + 1;

  const togglePassages = async () => {
    const next = !passagesOpen;
    setPassagesOpen(next);
    if (!next || passages || passagesError || !question) return;
    try {
      setPassages(await fetchPassages(question, bookId, 5));
    } catch {
      setPassagesError(true);
    }
  };

  const jumpToPassage = (passage: PassageHit) => {
    handleChip({
      chunk_id: passage.chunk_id,
      chapter: passage.chapter,
      quote: passage.text,
    });
  };

  const quotes = useMemo(() => {
    const list: { text: string; citation: Citation }[] = [];
    if (split.ok) {
      for (const item of split.items) {
        if (item.kind === "quote") {
          list.push({ text: item.text, citation: item.citation });
        }
      }
    } else {
      const parsed = splitAskAnswer(body.answer);
      if (parsed.quote) {
        list.push({
          text: parsed.quote,
          citation:
            body.citations[0] || {
              chunk_id: "",
              chapter: parsed.chapter || "Book",
              quote: parsed.quote,
            },
        });
      }
    }

    if (anchorQuote && anchorQuote.trim().length > 0) {
      const trimmed = anchorQuote.trim();
      const alreadyPresent = list.some(
        (q) => sameWords(q.text, trimmed) || sameWords(q.citation.quote, trimmed)
      );
      if (!alreadyPresent) {
        const citation =
          body.citations.find(
            (c) => c.quote && sameWords(c.quote, trimmed)
          ) ||
          body.citations[0] || {
            chunk_id: "",
            chapter: "Book",
            quote: trimmed,
          };
        list.unshift({ text: trimmed, citation });
      }
    }

    return list;
  }, [split, body.answer, body.citations, anchorQuote]);

  const sourcesCount = passages
    ? passages.length + quotes.length
    : Math.max(body.citations.length, quotes.length);
  const hasSources = Boolean(
    question || quotes.length > 0 || body.citations.length > 0
  );

  return (
    <div className="answer-view">
      {split.ok ? (
        split.items.map((item, index) => {
          if (item.kind === "gloss") {
            return (
              <p className="answer" key={index}>
                {item.text}
              </p>
            );
          }
          if (item.kind === "disclosure") {
            return (
              <p className="answer-disclosure" key={index}>
                {item.text}
              </p>
            );
          }
          return null;
        })
      ) : (
        (() => {
          const parsed = splitAskAnswer(body.answer);
          return (
            <>
              {parsed.gloss ? (
                <p className="answer">
                  {parsed.gloss}
                </p>
              ) : null}
              {!parsed.gloss && !parsed.quote ? (
                <p className="answer">
                  {body.answer}
                </p>
              ) : null}
              {parsed.disclosure ? (
                <p className="answer-disclosure">
                  {parsed.disclosure}
                </p>
              ) : null}

              {body.refused && body.citations.length ? (
                <p className="chips">
                  <span className="meta">
                    nearest misses:{" "}
                  </span>
                  {body.citations.map((citation, index) => (
                    <button
                      key={`${citation.chunk_id}-${index}`}
                      type="button"
                      className="chip chip-miss"
                      title={
                        citation.quote
                          ? citation.quote.slice(0, 140)
                          : `Jump to Ch. ${citation.chapter}`
                      }
                      onClick={(e) => {
                        e.stopPropagation();
                        handleChip(citation);
                      }}
                    >
                      {chipLabel(citation, index + 1, numbered)}
                    </button>
                  ))}
                </p>
              ) : null}
            </>
          );
        })()
      )}

      {body.refused && body.figures.length ? (
        <p className="meta">
          nearby, not an answer
        </p>
      ) : null}

      {body.figures.map((figure) => {
        const isHidden = Boolean(hiddenFigures[figure.id]);
        const figureLabel = figure.caption
          ? figure.caption
          : `Figure ${figure.id.replace(/^figure-/, "")}`;

        return (
          <div key={figure.id} className="figure-container">
            <div className="figure-toggle-row">
              <button
                type="button"
                className="figure-toggle-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  setHiddenFigures((prev) => ({
                    ...prev,
                    [figure.id]: !prev[figure.id],
                  }));
                }}
                aria-expanded={!isHidden}
                title={isHidden ? "Show figure" : "Hide figure"}
              >
                <span className="figure-toggle-icon" aria-hidden="true">
                  {isHidden ? "▸" : "▾"}
                </span>
                <span className="figure-toggle-label">
                  {isHidden ? `Show figure · ${figureLabel}` : "Hide figure"}
                </span>
              </button>
            </div>
            <div
              className={`figure-collapse-wrap ${
                isHidden ? "is-collapsed" : "is-open"
              }`}
            >
              <div className="figure-collapse-inner">
                <figure className="answer-figure">
                  <img
                    src={`${activeEngine}${figure.src}`}
                    alt={figure.caption || figure.id}
                    width={figure.width}
                    height={figure.height}
                    loading="lazy"
                    decoding="async"
                    className="answer-figure-img"
                  />
                  {figure.caption ? (
                    <figcaption className="answer-figure-caption">
                      {figure.caption}
                    </figcaption>
                  ) : null}
                </figure>
              </div>
            </div>
          </div>
        );
      })}

      {hasSources ? (
        <>
          <div className="sources-actions-row">
            <button
              type="button"
              className={`sources-pill-btn ${passagesOpen ? "is-open" : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                void togglePassages();
              }}
              aria-expanded={passagesOpen}
              title="Show source quotes and book passages"
            >
              <span>
                Sources
                {sourcesCount > 0 ? (
                  <span className="sources-count">{sourcesCount}</span>
                ) : null}
              </span>
              <svg
                className={`sources-chevron ${passagesOpen ? "is-open" : ""}`}
                width="12"
                height="12"
                viewBox="0 0 16 16"
                fill="none"
                aria-hidden="true"
              >
                <path
                  d="M4 6l4 4 4-4"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>

            {onCopy ? (
              <button
                type="button"
                className="sources-copy-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  onCopy();
                }}
                aria-label={copied ? "Copied" : "Copy answer"}
                title={copied ? "Copied" : "Copy answer with citations"}
              >
                {copied ? (
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <path d="M3.5 8.5L6.5 11.5L12.5 4.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : (
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <rect x="5" y="5" width="8.5" height="8.5" rx="2" stroke="currentColor" strokeWidth="1.75" />
                    <path d="M11 5V3.5a1.5 1.5 0 00-1.5-1.5h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5" stroke="currentColor" strokeWidth="1.75" />
                  </svg>
                )}
                <span>{copied ? "Copied" : "Copy"}</span>
              </button>
            ) : null}
          </div>

          {passagesOpen ? (
            <div className="sources-list">
              {quotes.map((q, idx) => {
                const chLabel = formatChapter(q.citation.chapter);
                const cleanQuote = q.text.replace(/^["'“”‘’]+|["'“”‘’]+$/g, "").trim();
                return (
                  <div key={`q-${idx}`} className="source-card">
                    <div className="source-card-top">
                      <span className="source-card-badge">Source quote</span>
                      <span className="source-card-ch">{chLabel}</span>
                      <button
                        type="button"
                        className="source-jump-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleChip({
                            chunk_id: q.citation.chunk_id,
                            chapter: q.citation.chapter,
                            quote: q.citation.quote || cleanQuote,
                            nonce: Date.now(),
                          } as Citation);
                        }}
                      >
                        Jump
                      </button>
                    </div>
                    <div className="source-card-quote">“{cleanQuote}”</div>
                  </div>
                );
              })}
              {question && passagesError ? (
                <p className="passage-empty">Could not load passages.</p>
              ) : null}
              {question && !passages && !passagesError ? (
                <p className="passage-empty">Reading the index…</p>
              ) : null}
              {(passages ?? []).map((passage) => (
                <div key={passage.chunk_id} className="source-card">
                  <div className="source-card-top">
                    <span className="source-card-ch">{formatChapter(passage.chapter)}</span>
                    {passage.heading ? (
                      <span className="source-card-title">{passage.heading}</span>
                    ) : null}
                    <button
                      type="button"
                      className="source-jump-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        jumpToPassage(passage);
                      }}
                    >
                      Jump
                    </button>
                  </div>
                  <div className="source-card-text">{passage.text.replace(/\s+/g, " ").trim()}</div>
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
