"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { Chunk } from "@/lib/engine";
import { useAsk } from "@/lib/store";

type ComposerProps = {
  getAnchorChunk: () => { chunkId: string; chapter: string; heading?: string };
  chunks?: Chunk[];
};

const BASE_SUGGESTIONS = [
  "What is a watermark?",
  "What does CRUD stand for?",
  "What are the stages of the data engineering lifecycle?",
];

const VALID_QUESTION_PREFIX = /^(?:What|How|Why|When|Where|Which|Who)\s/;

function extractQuestions(
  chunks: Chunk[] | undefined,
  activeChunkId: string,
  activeChapter: string
): string[] {
  if (!chunks || chunks.length === 0) return [];
  const matched: string[] = [];
  const seen = new Set<string>();

  const activeChunk = chunks.find((c) => c.chunk_id === activeChunkId);
  const chapterChunks = chunks.filter(
    (c) => c.chapter === activeChapter && c.chunk_id !== activeChunkId
  );
  const prioritized = activeChunk
    ? [activeChunk, ...chapterChunks]
    : chapterChunks;

  for (const c of prioritized) {
    const sentences = c.text.match(/([A-Z][^.?!;\n]{10,100}\?)/g);
    if (sentences) {
      for (const s of sentences) {
        const clean = s.trim().replace(/\s+/g, " ");
        if (
          clean.length >= 18 &&
          clean.length <= 62 &&
          VALID_QUESTION_PREFIX.test(clean) &&
          !seen.has(clean.toLowerCase())
        ) {
          seen.add(clean.toLowerCase());
          matched.push(clean);
          if (matched.length >= 3) {
            return matched.slice(0, 3);
          }
        }
      }
    }
  }
  return matched.slice(0, 3);
}

export default function Composer({ getAnchorChunk, chunks }: ComposerProps) {
  const mode = useAsk((s) => s.mode);
  const setMode = useAsk((s) => s.setMode);
  const submitWholeBook = useAsk((s) => s.submitWholeBook);
  const startQuiz = useAsk((s) => s.startQuiz);
  const engineReady = useAsk((s) => s.engineReady);

  const [draft, setDraft] = useState("");
  const [focused, setFocused] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const isRevealed = Boolean(isHovered || focused || draft.trim().length > 0);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea, [contenteditable]")) return;

      if (
        e.key === "/" ||
        ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")
      ) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    return () => {
      useAsk.getState().stopHealthPolling?.();
    };
  }, []);

  const anchor = getAnchorChunk();
  const dynamicQuestions = useMemo(() => {
    return extractQuestions(chunks, anchor.chunkId, anchor.chapter);
  }, [chunks, anchor.chunkId, anchor.chapter]);

  const allSuggestions = useMemo(() => {
    const combined = [...dynamicQuestions, ...BASE_SUGGESTIONS];
    const seen = new Set<string>();
    const dedupe: string[] = [];
    for (const s of combined) {
      const lower = s.toLowerCase();
      if (!seen.has(lower)) {
        seen.add(lower);
        dedupe.push(s);
      }
    }
    return dedupe;
  }, [dynamicQuestions]);

  const activeSuggestions = useMemo(() => {
    const q = draft.trim().toLowerCase();
    if (!q) {
      return allSuggestions.slice(0, 3);
    }
    const filtered = allSuggestions.filter((s) => s.toLowerCase().includes(q));
    filtered.sort((a, b) => {
      const aStarts = a.toLowerCase().startsWith(q) ? 0 : 1;
      const bStarts = b.toLowerCase().startsWith(q) ? 0 : 1;
      return aStarts - bStarts;
    });
    return filtered.slice(0, 3);
  }, [draft, allSuggestions]);

  const handleAsk = (questionText: string) => {
    const text = questionText.trim();
    if (!text) return;
    const currentAnchor = getAnchorChunk();
    submitWholeBook(
      currentAnchor.chunkId,
      currentAnchor.chapter,
      text,
      currentAnchor.heading || ""
    );
    setDraft("");
    inputRef.current?.blur();
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    handleAsk(draft);
  };

  const handleQuiz = () => {
    const currentAnchor = getAnchorChunk();
    startQuiz(currentAnchor.chunkId, currentAnchor.chapter);
  };

  return (
    <div
      className={`composer-dock ${isRevealed ? "is-revealed" : ""}`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <button
        type="button"
        className="composer-peek-tab"
        onClick={() => inputRef.current?.focus()}
        aria-label="Ask whole book"
        title="Ask whole book (/ to focus)"
      >
        <span className="composer-peek-label">Ask whole book</span>
        <span className="composer-peek-dot">·</span>
        <kbd className="composer-peek-kbd">/</kbd>
      </button>

      {focused && activeSuggestions.length > 0 && (
        <div className="composer-suggestions">
          {activeSuggestions.map((s) => (
            <button
              key={s}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => handleAsk(s)}
              className="composer-suggestion-pill"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <form onSubmit={handleSubmit} className="composer-form">
        {!engineReady && (
          <span className="composer-warming" aria-live="polite">
            Warming up…
          </span>
        )}
        <input
          ref={inputRef}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => {

            setTimeout(() => setFocused(false), 200);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              inputRef.current?.blur();
            }
          }}
          placeholder={engineReady ? "Ask about the whole book… (/ to focus)" : "Warming up…"}
          disabled={!engineReady}
          aria-label="Ask about the whole book"
          className="composer-input"
        />

        <button
          type="button"
          onClick={() => setMode(mode === "answer" ? "ask" : "answer")}
          title="Toggle mode between Answer and Quote first"
          className="composer-chip"
        >
          {mode === "answer" ? "Answer" : "Quote first"}
        </button>

        <button
          type="button"
          onClick={handleQuiz}
          disabled={!engineReady}
          title="Start quiz on current chapter passage"
          className="composer-chip"
        >
          Quiz
        </button>

        <button
          type="submit"
          disabled={!engineReady || !draft.trim()}
          aria-label="Submit question"
          className="composer-submit"
        >
          ↑
        </button>
      </form>
    </div>
  );
}
