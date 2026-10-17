"use client";

import { useMemo } from "react";
import { formatChapter } from "@/lib/anchor";
import { splitAnswer } from "@/lib/answer";
import { engineUrl, type AnswerBody, type Citation } from "@/lib/engine";
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
}: {
  body: AnswerBody;
  onChip?: (citation: Citation) => void;
  engine?: string;
  selection?: string;
  anchorQuote?: string;
}) {
  const storeShowCitation = useAsk((s) => s.showCitation);
  const handleChip = onChip ?? storeShowCitation;
  const activeEngine = engine ?? engineUrl();
  const activeQuote = anchorQuote || selection || "";

  const split = useMemo(() => splitAnswer(body), [body]);
  const numbered = body.citations.length > 1;
  const indexOf = (citation: Citation) => body.citations.indexOf(citation) + 1;

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
                  onClick={() => handleChip(item.citation)}
                >
                  {chipLabel(item.citation, indexOf(item.citation), numbered)}
                </button>
              </p>
            );
          }
          return (
            <p
              className="answer-quote"
              key={index}
              role="button"
              tabIndex={0}
              onClick={() =>
                handleChip({
                  chunk_id: item.citation.chunk_id,
                  chapter: item.citation.chapter,
                  quote: item.citation.quote,
                  nonce: Date.now(),
                } as Citation)
              }
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleChip({
                    chunk_id: item.citation.chunk_id,
                    chapter: item.citation.chapter,
                    quote: item.citation.quote,
                    nonce: Date.now(),
                  } as Citation);
                }
              }}
              title="Show this passage in the book"
            >
              <span className="answer-quote-text">“{item.text}”</span>{" "}
              <span className="chip">
                {chipLabel(item.citation, indexOf(item.citation), numbered)}
              </span>
            </p>
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
                <p
                  className="answer-quote"
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    const c = body.citations[0];
                    if (c) {
                      handleChip({
                        chunk_id: c.chunk_id,
                        chapter: c.chapter,
                        quote: c.quote || parsed.quote || "",
                        nonce: Date.now(),
                      } as Citation);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      const c = body.citations[0];
                      if (c) {
                        handleChip({
                          chunk_id: c.chunk_id,
                          chapter: c.chapter,
                          quote: c.quote || parsed.quote || "",
                          nonce: Date.now(),
                        } as Citation);
                      }
                    }
                  }}
                  title="Show this passage in the book"
                >
                  <span className="answer-quote-text">“{parsed.quote}”</span>
                  {parsed.chapter ? (
                    <span className="chip">Ch. {formatChapter(parsed.chapter)}</span>
                  ) : null}
                </p>
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
                      onClick={() => handleChip(citation)}
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

      {body.figures.map((figure) => (
        <figure key={figure.id} className="answer-figure">
          <img
            src={`${activeEngine}${figure.src}`}
            alt={figure.caption || figure.id}
            width={figure.width}
            height={figure.height}
            loading="lazy"
            className="answer-figure-img"
          />
          {figure.caption ? (
            <figcaption className="answer-figure-caption">
              {figure.caption}
            </figcaption>
          ) : null}
        </figure>
      ))}
    </div>
  );
}
