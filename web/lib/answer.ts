import type { AnswerBody, Citation } from "./engine";
import { quotePattern } from "./quote";

/** A parsed piece of an answer, in the order it should render.
 *
 *  The engine writes quote-first: `[Ch. N] "…quote…"` then a gloss line, then
 *  any `Asked as:` / `Read as:` disclosures. Reader-first rendering shows the
 *  gloss, then the quote in italics with its chapter chip; the words are the
 *  engine's own, only the order and styling change (owner decision
 *  2026-10-15). */
export type AnswerItem =
  | { kind: "gloss"; text: string }
  | { kind: "quote"; citation: Citation; text: string }
  | { kind: "disclosure"; text: string };

export type AnswerSplit =
  | { ok: true; items: AnswerItem[] }
  | { ok: false; items: AnswerItem[] };

/** The engine's machine-visible disclosures, appended at the answer's end. */
const DISCLOSURE = /^(Asked as|Read as):/;
/** The tag closing a quote-first line — `[Ch. 7] "` — removed so the chip is
 *  the only chapter mark left. */
const TAG_BEFORE_QUOTE = /\[Ch\.[^\]]*\]\s*"?$/;
/** The closing quotation mark right after a quote's span. */
const MARK_AFTER_QUOTE = /^\s*"/;

/**
 * Reorder an answer for reading: gloss first, then its evidence quote.
 *
 * The layout is recovered from the engine's own text: each citation's quote is
 * found in the answer (whitespace-insensitively, in order), and the text
 * between matches is the gloss. When a refusal, a missing quote, or a quote
 * the answer does not contain makes that recovery impossible, `ok` is false
 * and the caller shows the verbatim answer plus the chips row — a citation is
 * never lost.
 */
export function splitAnswer(body: AnswerBody): AnswerSplit {
  const kept: string[] = [];
  const disclosures: AnswerItem[] = [];
  for (const line of body.answer.split("\n")) {
    if (DISCLOSURE.test(line)) {
      disclosures.push({ kind: "disclosure", text: line.trim() });
    } else {
      kept.push(line);
    }
  }
  const text = kept.join("\n");

  const cited = body.citations.filter((citation) => citation.quote.trim());
  if (body.refused || cited.length === 0) return { ok: false, items: [] };

  // Find each quote in the answer, in order; each search starts after the
  // previous match's end.
  const matches: { citation: Citation; start: number; end: number }[] = [];
  let cursor = 0;
  for (const citation of cited) {
    const match = quotePattern(citation.quote).exec(text.slice(cursor));
    if (!match) return { ok: false, items: [] };
    const start = cursor + match.index;
    matches.push({ citation, start, end: start + match[0].length });
    cursor = start + match[0].length;
  }

  // Cut the text at the match spans: segments[0] leads the first quote and
  // segments[i] follows quote i-1 / leads quote i.
  const segments: string[] = [];
  let pos = 0;
  for (const match of matches) {
    segments.push(text.slice(pos, match.start));
    pos = match.end;
  }
  segments.push(text.slice(pos));

  const cleaned = segments.map((segment, index) => {
    let value = segment;
    if (index > 0) value = value.replace(MARK_AFTER_QUOTE, "");
    if (index < matches.length) value = value.replace(TAG_BEFORE_QUOTE, "");
    return value.trim();
  });

  const items: AnswerItem[] = [];
  if (cleaned[0]) items.push({ kind: "gloss", text: cleaned[0] });
  matches.forEach((match, index) => {
    // The gloss that followed the quote in the engine's text leads it here.
    const gloss = cleaned[index + 1];
    if (gloss) items.push({ kind: "gloss", text: gloss });
    items.push({
      kind: "quote",
      citation: match.citation,
      text: text.slice(match.start, match.end),
    });
  });
  items.push(...disclosures);

  return { ok: true, items };
}
