# Frontend build plan — following Gloss (2026-10-15; approved)

## The direction (user, 2026-10-15)

Build the frontend: the reader + chat window, following **Gloss** (Nutlope) — a
reader where answers sit beside the text and citations are checkable.
References: Gloss (the pattern), ReadAny (split + ambient context), NotebookLM
(source + chat), Readwise (clean reading), taste-skill (design taste — now a
project skill at `.agents/skills/book-companion-ui/`), prompt-kit + interior.dev
(AI-UI craft: the state model and the half-second details).

## Stack decision (decided: Next.js exception, user 2026-10-15)

**The UI is a Next.js app under `web/`** — the repo's no-build rule is
excepted for the frontend only (AGENTS.md hard rules). The engine, server, and
tests stay stdlib Python.

- Stack, following Gloss: Next.js (App Router), React, Tailwind, Zustand.
  Node 22 + npm live in `web/` only; the rest of the repo stays toolchain-free.
- The UI is client-side: it talks to the Python engine over HTTP.
  Development runs two processes (`next dev` on :3100 + `python server.py` on
  :8000); the browser calls the engine directly, so the engine gains one CORS
  header for localhost (it binds to 127.0.0.1 anyway). In production the
  engine serves the built static export, so the user still opens one URL
  (localhost:8000) and one process runs.
- `window/index.html` (the vanilla window) stays working until the Next app
  covers all four modes, then it is removed or kept as a plain fallback —
  decide at the swap.

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

**Phase 1 — the reader exists (landed 2026-10-15; owner eyeball pending).**
- Engine: `GET /chunks` — the index's chunks in reading order (id, chapter,
  heading, text, figures per chunk), read-only, derived from `data/index.json`;
  **`stream=1` on `/ask`** — NDJSON frames (`token`, `reset` when the retry
  fires, `final` carrying the parsed body, `error`); the non-stream path is
  untouched. Citations need no new field: `chunk_id` + `chapter` already
  address a rendered block.
- `web/` app: two panes (book blocks + chat); chunks rendered as blocks
  (`data-chunk-id`), figures inline per chunk; `[Ch. N]` chips from
  `citations[].chapter`; click → scroll to the block, find the verbatim
  `quote`, highlight it (CSS Custom Highlight API, fallback to a `<mark>`
  wrap); streaming answer with an honest latency line and a stop control;
  refusal/miss labels stay subordinate.
- Tests: `/chunks` route + the streaming frames (engine side, stdlib); suite
  green; restart the engine per the reset rule before judging.
- Success test: click any citation in any answer → land on the highlighted
  sentence in the re-rendered book, figures inline.
- **Landed 2026-10-15**: the engine half (`GET /chunks` — 1042 chunks,
  1,187,166 bytes, no vectors, heading line stripped, figure cards; `stream=1`
  NDJSON token/reset/final/error — live `final.body` equal to the non-stream
  body; CORS/OPTIONS for :3100) and the `web/` scaffold (Next 16 / React 19 /
  Tailwind 4 / Zustand, `output: "export"`, build green). Record:
  `../reports/frontend-phase1-2026-10-15.md`.
- **Reader block rules settled** (first-hand measurements 2026-10-15): one
  block per chunk (0 of 1025 same-doc consecutive pairs overlap); every chunk
  text leads with its heading (1042/1042), so the heading line is stripped
  server-side and `heading` renders only when it changes; 111 chunks carry
  figure cards; `chunk["anchor"]` is empty for all 1042 — the citation jump is
  the `chunk_id` block + a verbatim-quote DOM search.
- **Panes landed later the same day**: reader + ask run at
  `http://localhost:3100` (dev; engine on :8000) — streaming with the reset
  explained, citation chips → jump + quote mark, figures reserved by real PNG
  size. Success-test evidence: the citation-quote matcher finds 3/3 real
  quotes (python replica), `npm run build` green, 233 tests OK. The look is
  unverified (no browser automation on this box).

**Phase 2 — the margin + the lens (v1 landed 2026-10-15; stacking still open).**
- Answer cards beside the passage (Gloss's placement: active at anchor, others
  stacked, 16px gaps, mini when crowded), leader line in the gutter, select →
  ask (fills the explain box), mini cards.
- Landed: the selection lens (typed = `ask`, empty = `explain`), a single
  anchored card (streaming, leader line, only when the margin fits; the ask
  pane stays quiet while it shows), the resizable ask pane (288–720px,
  persisted). Open: collision stacking for several cards, the mini-crowd rule,
  char-offset anchors.

**Phase 3 — streaming + polish.**
- `stream=1` NDJSON from `/ask` (see open decisions), the interior.dev details
  (frame-one layout so streaming never shifts layout, stop control, copy with
  citation, honest latency line), the keyboard map, focus mode, themes.
- Landed 2026-10-15: the one-stream hold (tokens only for the answer's
  generation; the `[Ch. ` prefill leads the retry's stream; quiz held), the
  honest latency lines (first words + answered in), Stop, the
  reduced-motion stand-down. Open: copy-with-citation, the keyboard map,
  focus mode, themes.

**Phase 4 — book import / library.**
- Pick an EPUB on the page → ingest with progress → the book appears; multi-book
  picker. Needs: `ingest.py` parameterization (book_id, output path), per-book
  indexes, an upload route (multipart in stdlib), and a library UI.

## Research notes (2026-10-15 — three read-only agent audits; full notes in the record)

- **Gloss copy list** (`main @ 54b13b8`): the anchor model
  (`{start:{b,o}, end:{b,o}, quote}`) + `spanIn`/`segments()` mark splitting;
  `Margin.compute`/`place` geometry (active card pinned, 16px gaps, mini cards
  when passages start within 88px, bezier leader lines); `Cite` + `Peek`
  (hover preview, click-to-jump + flash, unknown ids disabled); `Lens`
  ("just type" capture, docked on coarse pointers); `ask.ts` streaming loop
  (TextDecoder, rAF token batching, one AbortController per card, interrupted
  repair); `GlossCard` states. **Skip**: Clerk/quota/keys, web search + `[1]`
  sources, sync/Postgres, importers, `docPayload` windowing.
- **No AI SDK** — Gloss streams raw SSE from its own route handler; our client
  reads NDJSON with `fetch` + `TextDecoder` directly against the engine (a Next
  proxy route would buffer the stream).
- **Ask-flow states + numbers** (prompt-kit / interior.dev): idle → selection →
  composing → submitted (elapsed counter; `aria-busy`, never native `disabled`)
  → first token → streaming → complete / refusal / stopped / error; skeleton
  only after a 120ms delay, never under 380ms; caret in a zero-width inline
  box; textarea cap 240px; citation chips only on `final` (a `[Ch.` token is
  not proof); refusal derived only from `final.refused`; no percentage meter,
  no idle spinner over the ~25s cold load, no typewriter on a frozen response.
  prompt-kit verdict: copy the PromptInput pattern + stick-to-bottom behavior;
  skip the Radix/shadcn dependency and the chat-chrome components.
- **Latency numbers from 2026-10-12 are stale** under the 2-day gate — measure
  time-to-first-token live before hard-coding any wait-state copy.

### Open (asked 2026-10-15)

1. Components: hand-rolled (recommended) vs a shadcn/Radix base in `web/`.
2. Theme: paper-light only for phase 1, dark/auto in phase 3 — confirm.
3. The reader block rules above — confirm.

## Open decisions (resolved 2026-10-15)

1. **Stack**: Next.js exception — **approved**.
2. **Streaming** (`stream=1` NDJSON): **approved**.
3. **Reader text source**: **re-rendered blocks from the index** (Gloss-style
   anchors; the book's own layout is not kept).
4. **Phase 2 margin**: full Gloss margin (owner approval 2026-10-15;
   re-rendered blocks make the placement algorithm natural).
5. **Import order**: phase 4 as planned.

## The project skill

`.agents/skills/book-companion-ui/` — the taste layer (adapted from taste-skill,
MIT) plus this repo's bindings; every UI task should load it.
