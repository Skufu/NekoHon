"use client";

import { quotePattern } from "./quote";

export type MarkerColor = "yellow" | "green" | "blue" | "pink";

export type UserHighlight = {
  id: string;
  chunkId: string;
  chapter: string;
  start: number;
  end: number;
  quote: string;
  color: MarkerColor;
  createdAt: number;
};

export type Segment = {
  text: string;
  highlightColor?: MarkerColor;
  highlightId?: string;
  isGlossAnchor?: boolean;
  glossId?: string;
  isActiveGloss?: boolean;
  isActiveMark?: boolean;
};

export function formatChapter(ch: string): string {
  const clean = (ch || "").trim();
  if (!clean) return "Book";
  if (/^\d+$/.test(clean)) return `Ch. ${clean}`;
  if (clean.toLowerCase().startsWith("preface")) return "Preface";
  if (clean.toLowerCase().startsWith("appendix")) return "Appendix";
  if (clean.toLowerCase().startsWith("ch")) {
    const m = clean.match(/^ch0*(\d+)/i);
    if (m) return `Ch. ${m[1]}`;
  }
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

/**
 * Character length from the start of an element's text content to (node, offset).
 */
function offsetWithin(el: HTMLElement, node: Node, offset: number): number {
  const r = document.createRange();
  r.selectNodeContents(el);
  try {
    r.setEnd(node, offset);
  } catch {
    return 0;
  }
  return r.toString().length;
}

const isWordChar = (ch: string | undefined): boolean =>
  Boolean(ch && /[A-Za-z0-9]/.test(ch));

/**
 * Measures plain-text character offset (start, end) of range within chunkEl's
 * <p> elements (joined by \n between <p> tags), or within heading/caption elements.
 * Returns { start, end, quote }. If outside paragraphs (e.g. heading/caption), returns start: -1, end: -1.
 */
export function offsetInChunk(
  chunkEl: HTMLElement,
  range: Range
): { start: number; end: number; quote: string } | null {
  const rawQuote = range.toString();
  const quote = rawQuote.trim();
  if (!quote) return null;

  const startNode = range.startContainer;
  const startEl =
    startNode instanceof Element ? startNode : startNode.parentElement;
  const isInsideP = Boolean(startEl?.closest(".chunk p, .chunk-p, p"));

  const paragraphs = Array.from(
    chunkEl.querySelectorAll<HTMLParagraphElement>("p, .chunk-p")
  );

  if (isInsideP && paragraphs.length > 0) {
    const fullText = paragraphs.map((p) => p.textContent ?? "").join("\n");
    let start: number | null = null;
    let end: number | null = null;
    let running = 0;

    for (let i = 0; i < paragraphs.length; i++) {
      const p = paragraphs[i];
      const pLen = p.textContent?.length ?? 0;

      if (start === null) {
        if (p.contains(range.startContainer)) {
          start = running + offsetWithin(p, range.startContainer, range.startOffset);
        } else {
          try {
            // comparePoint(p, 0) === 0 means (p, 0) is inside the range
            // (selection started in the parent container right before p)
            if (range.comparePoint(p, 0) === 0) {
              start = running;
            }
          } catch {
            // Ignore comparePoint errors across detached nodes
          }
        }
      }

      if (p.contains(range.endContainer)) {
        end = running + offsetWithin(p, range.endContainer, range.endOffset);
      } else if (start !== null && end === null) {
        try {
          if (range.comparePoint(p, p.childNodes.length) === 0) {
            end = running + pLen;
          }
        } catch {
          // Ignore comparePoint errors
        }
      }

      running += pLen + (i < paragraphs.length - 1 ? 1 : 0);
    }

    if (start === null || end === null) {
      const span = findQuoteSpan(fullText, quote);
      if (span) {
        start = span[0];
        end = span[1];
      } else {
        return null;
      }
    }

    // Trim leading/trailing whitespace directly in fullText before word-snap:
    while (start < end && /\s/.test(fullText[start])) start++;
    while (end > start && /\s/.test(fullText[end - 1])) end--;

    // Auto-snap partial words to whole word boundaries:
    if (start > 0 && isWordChar(fullText[start - 1]) && isWordChar(fullText[start])) {
      let steps = 0;
      while (
        start > 0 &&
        isWordChar(fullText[start - 1]) &&
        fullText[start - 1] !== "\n" &&
        steps < 15
      ) {
        start--;
        steps++;
      }
    }

    if (end < fullText.length && isWordChar(fullText[end - 1]) && isWordChar(fullText[end])) {
      let steps = 0;
      while (
        end < fullText.length &&
        isWordChar(fullText[end]) &&
        fullText[end] !== "\n" &&
        steps < 15
      ) {
        end++;
        steps++;
      }
    }

    // Trim leading and trailing whitespace (including \n)
    while (start < end && /\s/.test(fullText[start])) start++;
    while (end > start && /\s/.test(fullText[end - 1])) end--;

    // Paragraph boundary snap: if selection starts with a short lead-in or heading ending in : (<= 32 chars)
    // and spans into the next paragraph, snap start to the second paragraph.
    const rawSlice = fullText.slice(start, end);
    if (rawSlice.includes("\n")) {
      const firstNl = rawSlice.indexOf("\n");
      const firstLine = rawSlice.slice(0, firstNl).trim();
      const restSlice = rawSlice.slice(firstNl + 1).trim();
      if (restSlice.length > 0 && (firstLine.endsWith(":") || firstLine.length <= 32)) {
        start += firstNl + 1;
        while (start < end && /\s/.test(fullText[start])) start++;
      }
    }

    while (start < end && /\s/.test(fullText[start])) start++;
    while (end > start && /\s/.test(fullText[end - 1])) end--;

    const snappedQuote = fullText.slice(start, end).replace(/\s+/g, " ").trim();
    if (start >= end || !snappedQuote) return null;
    return { start, end, quote: snappedQuote };
  }

  // Check if selection is inside heading (.chunk-heading, h2)
  const headingEl =
    startEl?.closest<HTMLElement>("h2, .chunk-heading") ||
    (range.commonAncestorContainer instanceof Element
      ? range.commonAncestorContainer.closest<HTMLElement>("h2, .chunk-heading")
      : range.commonAncestorContainer.parentElement?.closest<HTMLElement>("h2, .chunk-heading"));

  if (headingEl && chunkEl.contains(headingEl)) {
    const containerText = headingEl.textContent || "";
    let hStart = offsetWithin(headingEl, range.startContainer, range.startOffset);
    let hEnd = offsetWithin(headingEl, range.endContainer, range.endOffset);
    if (hStart > hEnd) {
      const tmp = hStart;
      hStart = hEnd;
      hEnd = tmp;
    }

    if (hStart < hEnd && containerText) {
      while (hStart < hEnd && /\s/.test(containerText[hStart])) hStart++;
      while (hEnd > hStart && /\s/.test(containerText[hEnd - 1])) hEnd--;

      if (hStart > 0 && isWordChar(containerText[hStart - 1]) && isWordChar(containerText[hStart])) {
        let steps = 0;
        while (
          hStart > 0 &&
          isWordChar(containerText[hStart - 1]) &&
          containerText[hStart - 1] !== "\n" &&
          steps < 15
        ) {
          hStart--;
          steps++;
        }
      }
      if (
        hEnd < containerText.length &&
        isWordChar(containerText[hEnd - 1]) &&
        isWordChar(containerText[hEnd])
      ) {
        let steps = 0;
        while (
          hEnd < containerText.length &&
          isWordChar(containerText[hEnd]) &&
          containerText[hEnd] !== "\n" &&
          steps < 15
        ) {
          hEnd++;
          steps++;
        }
      }

      while (hStart < hEnd && /\s/.test(containerText[hStart])) hStart++;
      while (hEnd > hStart && /\s/.test(containerText[hEnd - 1])) hEnd--;

      const snappedHeadingQuote = containerText.slice(hStart, hEnd).trim();
      if (snappedHeadingQuote && hStart < hEnd) {
        return { start: -100 - hStart, end: -100 - hEnd, quote: snappedHeadingQuote };
      }
    }
  }

  // If the selection is outside paragraphs and headings (e.g. caption):
  const containerEl =
    startEl?.closest<HTMLElement>("figcaption, .chunk-caption") || chunkEl;
  const containerText = containerEl.textContent || "";
  let s = offsetWithin(containerEl, range.startContainer, range.startOffset);
  let e = offsetWithin(containerEl, range.endContainer, range.endOffset);

  if (s < e && containerText) {
    if (s > 0 && isWordChar(containerText[s - 1]) && isWordChar(containerText[s])) {
      let steps = 0;
      while (
        s > 0 &&
        isWordChar(containerText[s - 1]) &&
        containerText[s - 1] !== "\n" &&
        steps < 15
      ) {
        s--;
        steps++;
      }
    }
    if (
      e < containerText.length &&
      isWordChar(containerText[e - 1]) &&
      isWordChar(containerText[e])
    ) {
      let steps = 0;
      while (
        e < containerText.length &&
        isWordChar(containerText[e]) &&
        containerText[e] !== "\n" &&
        steps < 15
      ) {
        e++;
        steps++;
      }
    }
    const snappedCaptionQuote = containerText.slice(s, e).trim();
    if (snappedCaptionQuote) {
      return { start: -1, end: -1, quote: snappedCaptionQuote };
    }
  }

  return { start: -1, end: -1, quote };
}

export function isHeadingOffset(offset?: number): boolean {
  return typeof offset === "number" && offset <= -100;
}

export function decodeHeadingOffset(offset: number): number {
  return -100 - offset;
}

export type HighlightSpan = {
  chunkId: string;
  chapter: string;
  start: number;
  end: number;
  quote: string;
};

type SelectionResolution = {
  startChunkId: string;
  endChunkId?: string;
  chapter: string;
  heading: string;
  quote: string;
  start: number;
  end: number;
  spans: HighlightSpan[];
};

/**
 * Resolves a text selection range within containerEl, supporting both single-chunk
 * and cross-chunk selections across adjacent chunks.
 */
export function resolveSelection(
  containerEl: HTMLElement,
  range: Range
): SelectionResolution | null {
  const rawQuote = range.toString();
  const trimmed = rawQuote.trim();
  if (!trimmed) return null;

  const startNode = range.startContainer;
  const endNode = range.endContainer;
  const startEl =
    startNode instanceof Element ? startNode : startNode.parentElement;
  const endEl =
    endNode instanceof Element ? endNode : endNode.parentElement;
  if (!startEl || !endEl) return null;

  const startChunkEl = startEl.closest<HTMLElement>("[data-chunk-id]");
  const endChunkEl = endEl.closest<HTMLElement>("[data-chunk-id]");
  if (!startChunkEl || !endChunkEl) return null;
  if (!containerEl.contains(startChunkEl) || !containerEl.contains(endChunkEl)) {
    return null;
  }

  const getChunkMeta = (el: HTMLElement) => {
    const chunkId =
      el.dataset.chunkId || el.getAttribute("data-chunk-id") || "";
    let chapter =
      el.dataset.chapter || el.getAttribute("data-chapter") || "";
    if (!chapter) {
      const m = chunkId.match(/^ch0*(\d+)/);
      if (m) chapter = m[1];
    }
    const heading =
      el.dataset.heading ||
      el.getAttribute("data-heading") ||
      el.querySelector("h2")?.textContent ||
      "";
    return { chunkId, chapter, heading };
  };

  if (startChunkEl === endChunkEl) {
    const offsetRes = offsetInChunk(startChunkEl, range);
    if (!offsetRes) return null;
    const { chunkId, chapter, heading } = getChunkMeta(startChunkEl);
    const spans: HighlightSpan[] =
      offsetRes.start >= 0 || isHeadingOffset(offsetRes.start)
        ? [
            {
              chunkId,
              chapter,
              start: offsetRes.start,
              end: offsetRes.end,
              quote: offsetRes.quote,
            },
          ]
        : [];
    return {
      startChunkId: chunkId,
      chapter,
      heading,
      quote: offsetRes.quote,
      start: offsetRes.start,
      end: offsetRes.end,
      spans,
    };
  }

  const allChunks = Array.from(
    containerEl.querySelectorAll<HTMLElement>("[data-chunk-id]")
  );
  const sIdx = allChunks.indexOf(startChunkEl);
  const eIdx = allChunks.indexOf(endChunkEl);
  if (sIdx === -1 || eIdx === -1 || sIdx > eIdx) return null;

  const selectedChunks = allChunks.slice(sIdx, eIdx + 1);
  const spans: HighlightSpan[] = [];

  // 1. startChunkEl: from range.startContainer/startOffset to end of startChunkEl text
  const startMeta = getChunkMeta(startChunkEl);
  const startParagraphs = Array.from(
    startChunkEl.querySelectorAll<HTMLParagraphElement>("p, .chunk-p")
  );
  const startFullText =
    startParagraphs.length > 0
      ? startParagraphs.map((p) => p.textContent ?? "").join("\n")
      : startChunkEl.textContent ?? "";

  let startOffset: number | null = null;
  if (startParagraphs.length > 0) {
    let running = 0;
    for (let i = 0; i < startParagraphs.length; i++) {
      const p = startParagraphs[i];
      const pLen = p.textContent?.length ?? 0;
      if (startOffset === null && p.contains(range.startContainer)) {
        startOffset =
          running + offsetWithin(p, range.startContainer, range.startOffset);
      }
      running += pLen + (i < startParagraphs.length - 1 ? 1 : 0);
    }
  } else {
    startOffset = offsetWithin(
      startChunkEl,
      range.startContainer,
      range.startOffset
    );
  }
  if (startOffset === null) startOffset = 0;

  // Snap startOffset to word boundary at start
  if (
    startOffset > 0 &&
    startOffset < startFullText.length &&
    isWordChar(startFullText[startOffset - 1]) &&
    isWordChar(startFullText[startOffset])
  ) {
    let steps = 0;
    while (
      startOffset > 0 &&
      isWordChar(startFullText[startOffset - 1]) &&
      startFullText[startOffset - 1] !== "\n" &&
      steps < 15
    ) {
      startOffset--;
      steps++;
    }
  }

  let startEnd = startFullText.length;
  while (startEnd > startOffset && /\s/.test(startFullText[startEnd - 1])) {
    startEnd--;
  }

  const startQuote = startFullText.slice(startOffset, startEnd).trim();
  if (startQuote && startOffset < startEnd) {
    spans.push({
      chunkId: startMeta.chunkId,
      chapter: startMeta.chapter,
      start: startOffset,
      end: startEnd,
      quote: startQuote,
    });
  }

  // 2. Intermediate chunks (if any)
  for (let i = 1; i < selectedChunks.length - 1; i++) {
    const midChunk = selectedChunks[i];
    const midMeta = getChunkMeta(midChunk);
    const midParagraphs = Array.from(
      midChunk.querySelectorAll<HTMLParagraphElement>("p, .chunk-p")
    );
    const midFullText =
      midParagraphs.length > 0
        ? midParagraphs.map((p) => p.textContent ?? "").join("\n")
        : midChunk.textContent ?? "";
    const midQuote = midFullText.trim();
    if (midQuote) {
      spans.push({
        chunkId: midMeta.chunkId,
        chapter: midMeta.chapter,
        start: 0,
        end: midFullText.length,
        quote: midQuote,
      });
    }
  }

  // 3. endChunkEl: from 0 to range.endContainer/endOffset
  const endMeta = getChunkMeta(endChunkEl);
  const endParagraphs = Array.from(
    endChunkEl.querySelectorAll<HTMLParagraphElement>("p, .chunk-p")
  );
  const endFullText =
    endParagraphs.length > 0
      ? endParagraphs.map((p) => p.textContent ?? "").join("\n")
      : endChunkEl.textContent ?? "";

  let endOffset: number | null = null;
  if (endParagraphs.length > 0) {
    let running = 0;
    for (let i = 0; i < endParagraphs.length; i++) {
      const p = endParagraphs[i];
      const pLen = p.textContent?.length ?? 0;
      if (endOffset === null && p.contains(range.endContainer)) {
        endOffset =
          running + offsetWithin(p, range.endContainer, range.endOffset);
      }
      running += pLen + (i < endParagraphs.length - 1 ? 1 : 0);
    }
  } else {
    endOffset = offsetWithin(
      endChunkEl,
      range.endContainer,
      range.endOffset
    );
  }
  if (endOffset === null) endOffset = endFullText.length;

  // Snap endOffset to word boundary at end
  if (
    endOffset > 0 &&
    endOffset < endFullText.length &&
    isWordChar(endFullText[endOffset - 1]) &&
    isWordChar(endFullText[endOffset])
  ) {
    let steps = 0;
    while (
      endOffset < endFullText.length &&
      isWordChar(endFullText[endOffset]) &&
      endFullText[endOffset] !== "\n" &&
      steps < 15
    ) {
      endOffset++;
      steps++;
    }
  }

  let endStart = 0;
  while (endStart < endOffset && /\s/.test(endFullText[endStart])) {
    endStart++;
  }

  const endQuote = endFullText.slice(endStart, endOffset).trim();
  if (endQuote && endStart < endOffset) {
    spans.push({
      chunkId: endMeta.chunkId,
      chapter: endMeta.chapter,
      start: endStart,
      end: endOffset,
      quote: endQuote,
    });
  }

  const combinedQuote =
    spans.length > 0 ? spans.map((s) => s.quote).join(" ").trim() : trimmed;

  return {
    startChunkId: startMeta.chunkId,
    endChunkId: endMeta.chunkId,
    chapter: startMeta.chapter,
    heading: startMeta.heading,
    quote: combinedQuote,
    start: startOffset,
    end: endOffset,
    spans,
  };
}

/**
 * For cross-chunk selections, finds the matching quote span for a chunk playing
 * the "start" or "end" role.
 */
export function findQuoteSpanForRole(
  chunkText: string,
  quote: string,
  role: "start" | "end",
  nearOffset?: number
): [number, number] | null {
  if (!quote.trim() || !chunkText) return null;

  // First try direct quote span (if the chunk contains the quote)
  const direct = findQuoteSpan(chunkText, quote, nearOffset);
  if (direct) return direct;

  const words = quote.trim().split(/\s+/);
  if (words.length <= 1) {
    return findQuoteSpan(chunkText, quote, nearOffset);
  }

  if (role === "start") {
    // Look for the longest prefix of words that matches in chunkText
    for (let len = words.length - 1; len >= 1; len--) {
      const prefix = words.slice(0, len).join(" ");
      const span = findQuoteSpan(chunkText, prefix, nearOffset);
      if (span) return span;
    }
  } else {
    // role === "end": look for the longest suffix of words that matches in chunkText
    for (let start = 1; start < words.length; start++) {
      const suffix = words.slice(start).join(" ");
      const span = findQuoteSpan(chunkText, suffix);
      if (span) return span;
    }
  }

  return null;
}

function findWordOverlapSpan(
  rawText: string,
  quote: string,
  nearOffset?: number
): [number, number] | null {
  const rawQuoteWords = quote.toLowerCase().match(/[a-z0-9]+/g);
  if (!rawQuoteWords || rawQuoteWords.length === 0) return null;
  const contentWords = rawQuoteWords.filter((w) => w.length >= 3);
  const targetWords = contentWords.length >= 3 ? contentWords : rawQuoteWords;
  if (targetWords.length === 0) return null;

  const targetSet = new Set(targetWords);

  const textWords: { word: string; start: number; end: number }[] = [];
  const wordRegex = /[a-z0-9]+/gi;
  let m: RegExpExecArray | null;
  while ((m = wordRegex.exec(rawText)) !== null) {
    textWords.push({
      word: m[0].toLowerCase(),
      start: m.index,
      end: m.index + m[0].length,
    });
  }

  if (textWords.length === 0) return null;

  const windowLen = Math.max(3, rawQuoteWords.length);
  const minMatches = Math.max(2, Math.ceil(targetWords.length * 0.7));

  let bestSpan: [number, number] | null = null;
  let bestScore = 0;
  let bestDistance = Infinity;

  for (let i = 0; i <= textWords.length - Math.min(textWords.length, windowLen); i++) {
    const endIdx = Math.min(textWords.length - 1, i + windowLen - 1);
    const windowSlice = textWords.slice(i, endIdx + 1);

    let matches = 0;
    const seen = new Set<string>();
    for (const tw of windowSlice) {
      if (targetSet.has(tw.word) && !seen.has(tw.word)) {
        seen.add(tw.word);
        matches++;
      }
    }

    if (matches >= minMatches) {
      const score = matches / targetWords.length;
      const startChar = windowSlice[0].start;
      const endChar = windowSlice[windowSlice.length - 1].end;
      const distance = nearOffset != null ? Math.abs(startChar - nearOffset) : startChar;

      if (score > bestScore || (score === bestScore && distance < bestDistance)) {
        bestScore = score;
        bestDistance = distance;
        bestSpan = [startChar, endChar];
      }
    }
  }

  return bestSpan;
}

/**
 * Uses quotePattern(quote) from ./quote to find all matches in rawText,
 * returning [start, end] of the match closest to nearOffset (or first match if nearOffset == null).
 */
export function findQuoteSpan(
  rawText: string,
  quote: string,
  nearOffset?: number
): [number, number] | null {
  const trimmed = quote.trim();
  if (!trimmed) return null;

  if (nearOffset != null && nearOffset >= 0) {
    if (
      rawText.slice(nearOffset, nearOffset + trimmed.length).toLowerCase() ===
      trimmed.toLowerCase()
    ) {
      return [nearOffset, nearOffset + trimmed.length];
    }
    if (
      rawText.slice(nearOffset, nearOffset + quote.length).toLowerCase() ===
      quote.toLowerCase()
    ) {
      return [nearOffset, nearOffset + quote.length];
    }
    const nearSlice = rawText.slice(nearOffset, nearOffset + quote.length + 10);
    const nearMatch = quotePattern(quote).exec(nearSlice);
    if (nearMatch && nearMatch.index === 0) {
      return [nearOffset, nearOffset + nearMatch[0].length];
    }
  }

  const pattern = quotePattern(quote);
  const hits: { index: number; length: number }[] = [];
  for (const match of rawText.matchAll(new RegExp(pattern.source, "gi"))) {
    if (match.index !== undefined) {
      hits.push({ index: match.index, length: match[0].length });
    }
  }
  if (!hits.length) {
    return findWordOverlapSpan(rawText, quote, nearOffset);
  }

  if (nearOffset == null) {
    if (hits.length > 1) {
      const isWord = (ch: string | undefined) =>
        Boolean(ch && /[A-Za-z0-9]/.test(ch));
      const wordBounded = hits.find((h) => {
        const prev = h.index > 0 ? rawText[h.index - 1] : " ";
        const first = rawText[h.index];
        const last = rawText[h.index + h.length - 1];
        const next =
          h.index + h.length < rawText.length ? rawText[h.index + h.length] : " ";
        const startsOnWord = !isWord(prev) || !isWord(first);
        const endsOnWord = !isWord(next) || !isWord(last);
        return startsOnWord && endsOnWord;
      });
      if (wordBounded)
        return [wordBounded.index, wordBounded.index + wordBounded.length];
    }
    return [hits[0].index, hits[0].index + hits[0].length];
  }

  const hit = hits.reduce((best, item) =>
    Math.abs(item.index - nearOffset) < Math.abs(best.index - nearOffset)
      ? item
      : best
  );
  return [hit.index, hit.index + hit.length];
}

/**
 * Splits a paragraph's text at all boundary points falling within
 * [paragraphStart, paragraphStart + text.length] and returns Segment[]
 * so each slice carries highlightColor, highlightId, isGlossAnchor, glossId,
 * isActiveGloss, and isActiveMark.
 */
export function splitParagraphSegments(
  text: string,
  paragraphStart: number,
  options: {
    highlights: UserHighlight[];
    glossRanges: { id: string; start: number; end: number; active: boolean }[];
    citationRange: [number, number] | null;
  }
): Segment[] {
  if (!text) return [];

  const pStart = paragraphStart;
  const pEnd = paragraphStart + text.length;

  const cutPoints = new Set<number>([0, text.length]);

  // Collect cut points from user highlights
  for (const h of options.highlights) {
    if (h.start < pEnd && h.end > pStart) {
      const from = Math.max(0, Math.min(text.length, h.start - pStart));
      const to = Math.max(0, Math.min(text.length, h.end - pStart));
      if (from < to) {
        cutPoints.add(from);
        cutPoints.add(to);
      }
    }
  }

  // Collect cut points from gloss ranges
  for (const g of options.glossRanges) {
    if (g.start < pEnd && g.end > pStart) {
      const from = Math.max(0, Math.min(text.length, g.start - pStart));
      const to = Math.max(0, Math.min(text.length, g.end - pStart));
      if (from < to) {
        cutPoints.add(from);
        cutPoints.add(to);
      }
    }
  }

  // Collect cut points from citation range
  if (options.citationRange) {
    const [cStart, cEnd] = options.citationRange;
    if (cStart < pEnd && cEnd > pStart) {
      const from = Math.max(0, Math.min(text.length, cStart - pStart));
      const to = Math.max(0, Math.min(text.length, cEnd - pStart));
      if (from < to) {
        cutPoints.add(from);
        cutPoints.add(to);
      }
    }
  }

  const sortedPoints = Array.from(cutPoints).sort((a, b) => a - b);
  const segments: Segment[] = [];

  for (let i = 0; i < sortedPoints.length - 1; i++) {
    const from = sortedPoints[i];
    const to = sortedPoints[i + 1];
    if (from >= to) continue;

    const sliceText = text.slice(from, to);
    if (!sliceText) continue;

    const gFrom = pStart + from;
    const gTo = pStart + to;

    // Check user highlights: pick latest matching highlight
    let highlightColor: MarkerColor | undefined;
    let highlightId: string | undefined;
    for (let j = options.highlights.length - 1; j >= 0; j--) {
      const h = options.highlights[j];
      if (h.start <= gFrom && h.end >= gTo) {
        highlightColor = h.color;
        highlightId = h.id;
        break;
      }
    }

    // Check gloss ranges
    let isGlossAnchor: boolean | undefined;
    let glossId: string | undefined;
    let isActiveGloss: boolean | undefined;
    for (let j = options.glossRanges.length - 1; j >= 0; j--) {
      const g = options.glossRanges[j];
      if (g.start <= gFrom && g.end >= gTo) {
        isGlossAnchor = true;
        glossId = g.id;
        isActiveGloss = g.active;
        break;
      }
    }

    // Check citation range
    let isActiveMark: boolean | undefined;
    if (options.citationRange) {
      const [cStart, cEnd] = options.citationRange;
      if (cStart <= gFrom && cEnd >= gTo) {
        isActiveMark = true;
      }
    }

    const seg: Segment = {
      text: sliceText,
      ...(highlightColor ? { highlightColor, highlightId } : {}),
      ...(isGlossAnchor ? { isGlossAnchor, glossId, isActiveGloss } : {}),
      ...(isActiveMark ? { isActiveMark } : {}),
    };

    segments.push(seg);
  }

  return segments;
}
