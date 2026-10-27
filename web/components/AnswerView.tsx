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

function PassageRow({
  passage,
  rank,
  onJump,
}: {
  passage: PassageHit;
  rank: number;
  onJump: (passage: PassageHit) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const heading = (passage.heading || "").trim();
  const body = (passage.text || "").trim();
  const chapter = formatChapter(passage.chapter);
  const long = body.length > 240;

  const activate = (e: React.MouseEvent) => {
    // A drag that selects text is the reader marking a quote, not a jump.
    if (typeof window !== "undefined" && window.getSelection()?.toString().trim()) {
      return;
    }
    e.stopPropagation();
    onJump(passage);
  };

  return (
    <article className="passage-item" onClick={activate}>
      <span
        className="passage-rank"
        title={`cosine similarity ${passage.score.toFixed(4)}`}
        aria-hidden="true"
      >
        {rank}
      </span>
      <div className="passage-main">
        <div className="passage-lead">
          <span className="passage-heading">{heading}</span>
          <button
            type="button"
            className="passage-jump"
            onClick={(e) => {
              e.stopPropagation();
              onJump(passage);
            }}
            title={`Jump to this passage in ${chapter}`}
            aria-label={`Jump to this passage in ${chapter}`}
          >
            {chapter}
            <span className="passage-jump-arrow" aria-hidden="true">{"\u2192"}</span>
          </button>
        </div>
        <p className={`passage-text${long && !expanded ? " is-clamped" : ""}`}>{body}</p>
        {long ? (
          <button
            type="button"
            className="passage-more"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded((v) => !v);
            }}
            aria-expanded={expanded}
          >
            {expanded ? "Less" : "More"}
          </button>
        ) : null}
      </div>
    </article>
  );
}

function SourceQuoteSection({
  quote,
  citation,
  onJump,
}: {
  quote: string;
  citation: Citation;
  onJump: (citation: Citation) => void;
}) {
  const [open, setOpen] = useState(false);
  const chLabel = formatChapter(citation.chapter);
  const cleanQuote = quote.replace(/^["'“”‘’]+|["'“”‘’]+$/g, "").trim();

  const jump = (e: React.MouseEvent | React.KeyboardEvent) => {
    e.stopPropagation();
    onJump({
      chunk_id: citation.chunk_id,
      chapter: citation.chapter,
      quote: citation.quote || cleanQuote,
      nonce: Date.now(),
    } as Citation);
  };

  return (
    <div className="source-quote-wrap">
      <div className="source-pill-row">
        <button
          type="button"
          className={`source-pill ${open ? "is-open" : ""}`}
          onClick={(e) => {
            e.stopPropagation();
            setOpen((v) => !v);
          }}
          title={open ? "Hide source quote" : `Expand source quote · ${chLabel}`}
          aria-expanded={open}
        >
          <span className="source-pill-icon">{open ? "\u2212" : "+"}</span>
          <span className="source-pill-label">Source quote · {chLabel}</span>
        </button>
      </div>

      <div className={`source-popover-wrapper ${open ? "is-open" : ""}`} aria-hidden={!open}>
        <div className="source-popover-inner">
          <div className="source-popover">
            <blockquote
              className="source-popover-text"
              onClick={jump}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  jump(e);
                }
              }}
              title={`Jump to passage in ${chLabel}`}
            >
              “{cleanQuote}”
            </blockquote>
            <div className="source-popover-actions">
              <button
                type="button"
                className="source-jump-btn"
                onClick={jump}
                title={`Jump to passage in ${chLabel}`}
              >
                <span>Jump to passage in {chLabel}</span>
                <span className="source-jump-arrow" aria-hidden="true">{"\u2192"}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AnswerView({
  body,
  onChip,
  engine,
  selection = "",
  anchorQuote = "",
  question,
}: {
  body: AnswerBody;
  onChip?: (citation: Citation) => void;
  engine?: string;
  selection?: string;
  anchorQuote?: string;
  question?: string;
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
          const alreadySelected =
            activeQuote.length > 0 &&
            (sameWords(item.text, activeQuote) ||
              sameWords(item.citation.quote, activeQuote));
          if (alreadySelected) {
            return (
              <p className="meta" key={index}>
                <button
                  type="button"
                  className="chip"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleChip(item.citation);
                  }}
                >
                  {chipLabel(item.citation, indexOf(item.citation), numbered)}
                </button>
              </p>
            );
          }
          return (
            <SourceQuoteSection
              key={index}
              quote={item.text}
              citation={item.citation}
              onJump={handleChip}
            />
          );
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
              {parsed.quote ? (
                <SourceQuoteSection
                  quote={parsed.quote}
                  citation={
                    body.citations[0] || {
                      chunk_id: "",
                      chapter: parsed.chapter || "Book",
                      quote: parsed.quote,
                    }
                  }
                  onJump={handleChip}
                />
              ) : (
                !parsed.gloss ? (
                  <p className="answer">
                    {body.answer}
                  </p>
                ) : null
              )}
              {parsed.disclosure ? (
                <p className="answer-disclosure">
                  {parsed.disclosure}
                </p>
              ) : null}

              {body.citations.length ? (
                <p className="chips">
                  {body.refused ? (
                    <span className="meta">
                      nearest misses:{" "}
                    </span>
                  ) : null}
                  {body.citations.map((citation, index) => (
                    <button
                      key={`${citation.chunk_id}-${index}`}
                      type="button"
                      className={`chip ${body.refused ? "chip-miss" : ""}`}
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

      {question ? (
        <div className="passages-block">
          <button
            type="button"
            className="passages-toggle"
            onClick={(e) => {
              e.stopPropagation();
              void togglePassages();
            }}
            aria-expanded={passagesOpen}
            title="Show the passages retrieval offered for this question"
          >
            <span className="passages-toggle-icon" aria-hidden="true">
              {passagesOpen ? "\u2212" : "+"}
            </span>
            <span>Passages</span>
            {passages ? (
              <span className="passages-toggle-count">{passages.length}</span>
            ) : null}
          </button>
          {passagesOpen ? (
            <div className="passage-list">
              {passagesError ? (
                <p className="passage-empty">Could not load passages.</p>
              ) : null}
              {!passages && !passagesError ? (
                <p className="passage-empty">Reading the index…</p>
              ) : null}
              {passages && !passages.length ? (
                <p className="passage-empty">Nothing came back for this question.</p>
              ) : null}
              {(passages ?? []).map((passage, index) => (
                <PassageRow
                  key={passage.chunk_id}
                  passage={passage}
                  rank={index + 1}
                  onJump={jumpToPassage}
                />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
