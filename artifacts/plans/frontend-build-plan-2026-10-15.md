# Frontend build plan — following Gloss (2026-10-15; approved)

## The direction (user, 2026-10-15)

Build the frontend: the reader + chat window, following **Gloss** (Nutlope) — a
reader where answers sit beside the text and citations are checkable.
References: Gloss (the pattern), ReadAny (split + ambient context), NotebookLM
(source + chat), Readwise (clean reading), taste-skill (design taste — now a
project skill at `.agents/skills/book-companion-ui/`), prompt-kit + interior.dev
(AI-UI craft: the state model and the half-second details).

## Stack decision (recommended; confirm)

**Keep the Python engine; build the window in vanilla HTML/CSS/JS.** Following
Gloss means following its *patterns*, not its stack:

- Gloss: Next.js 16 / React 19 / Tailwind v4 / Zustand + cloud (Together AI) +
  accounts/sync. Ours: stdlib Python engine, local-only, offline, no build step.
- A React/Next shell needs an explicit exception, adds Node + npm + a build, and
  buys nothing the patterns don't already give — the whole UI is a few hundred
  lines of vanilla.
- If the UI ever outgrows vanilla (many components, real state), revisit with a
  written exception request. The API stays the same, so the shell is swappable.
- Allowed split per the repo rule: `window/app.css` + `window/app.js` with
  `<link>`/`<script>`; no bundler, no framework, no CDN import.

## What we take from Gloss (patterns, with source pointers)

1. **The margin is the interface** — an answer beside its passage, tied by a
   leader line; collision-resolved stacking (the active card at its anchor,
   others stack away, mini cards when crowded). `components/reader/Margin.tsx`.
   Phase 2.
2. **Citations are first-class UI** — `[Ch. N]` chips that jump to the passage
   and peek its text; unknown ids render disabled, not dead. `Answer.tsx`,
   `Overlays.tsx`. Phase 1.
3. **Select, then just type** — a floating lens at the selection; a keystroke
   opens the ask box; explain/define/simplify as one-tap tasks. `Lens.tsx`.
   Phase 2.
4. **Anchors** — Gloss uses block id + char offsets (`lib/anchor.ts`). We start
   with the citation's own verbatim `quote` as the selector (search inside the
   rendered page); offsets later (the locator plan's Phase B).
5. **Restraint** — one accent per role, hairline rules, motion only as feedback;
   CSS variables applied before first paint; `prefers-reduced-motion` stand-down.
   `app/globals.css`, `lib/settings.ts`.
6. **Citation checkability** — a citation is only worth claiming if one click
   proves it. Paragraph numbers as the shared address (ours: `[Ch. N]`).

## What we do NOT take

React/Zustand/Tailwind/Next; accounts and sync (this machine is the sync); the
link/PDF import pipeline (we have EPUB); cloud TTS (offline `speechSynthesis` if
ever wanted); the SSE frame taxonomy (shrink to content/done if streaming
ships); feedback bars, avatars, tool-call UI, reasoning panes.

## The build phases

**Phase 1 — the reader exists (next).**
- Engine: `GET /book/<path>` serving the EPUB's own files (XHTML/CSS/images)
  from `books/<book_id>.epub`, path-safe, MIME by extension; citations gain
  `doc` (additive, one enrichment helper in `answer.py`); `GET /spine` — the
  docs in reading order with titles, derived from the index.
- Window: two panes (book iframe + chat); `[Ch. N]` chips from
  `citations[].chapter`; click → open the doc, find the verbatim `quote`,
  highlight it (CSS Custom Highlight API, fallback to a `<mark>` wrap) and
  scroll; "back to the question" control; the refusal/miss labels stay
  subordinate (never restyle a miss as a citation).
- Tests: the new route (path safety + MIME), `doc` on citations; suite green;
  restart the engine per the reset rule before judging.
- Success test: click any citation in any answer → land on the highlighted
  sentence in the actual book, with figures inline.

**Phase 2 — the margin + the lens.**
- Answer cards beside the passage (Gloss's placement: active at anchor, others
  stacked, 16px gaps, mini when crowded), leader line in the gutter, select →
  ask (fills the explain box), mini cards.

**Phase 3 — streaming + polish.**
- `stream=1` NDJSON from `/ask` (see open decisions), the interior.dev details
  (frame-one layout so streaming never shifts layout, stop control, copy with
  citation, honest latency line), the keyboard map, focus mode, themes.

**Phase 4 — book import / library.**
- Pick an EPUB on the page → ingest with progress → the book appears; multi-book
  picker. Needs: `ingest.py` parameterization (book_id, output path), per-book
  indexes, an upload route (multipart in stdlib), and a library UI.

## Open decisions (user)

1. **Stack**: vanilla (recommended) vs a Next.js exception.
2. **Streaming** (`stream=1` NDJSON): the biggest perceived-quality win; a
   contract addition; Ollama streams natively.
3. **Reader text source**: the book's own XHTML in an iframe (recommended —
   fidelity, figures inline) vs re-rendered clean blocks (Gloss-style anchors,
   loses the book's layout).
4. **Phase 2 margin**: full Gloss margin, or chat-pane-first and the margin
   after phase 1 proves itself (recommended).
5. **Import order**: phase 4 as listed, or earlier.

## The project skill

`.agents/skills/book-companion-ui/` — the taste layer (adapted from taste-skill,
MIT) plus this repo's bindings; every UI task should load it.
