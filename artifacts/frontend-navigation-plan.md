# Frontend + citation navigation — direction (2026-10-13)

Status: direction recorded from the user's decisions; **not approved, nothing
wired**. Contract changes listed below need an explicit yes before any code.

## Goal

Citations stop being text. Clicking `[Ch. N]` opens the source passage in the
app's own reader, scrolled to the passage and highlighted. The same reader
becomes the frontend product — the window grows into it.

## Decisions taken (user, 2026-10-13)

- **External-reader hand-off is dropped.** Handing a citation to an installed
  third-party app (Apple Books, Calibre) via OS URL schemes was the old
  Phase 8 shape; it is dead. The app's own frontend is the reader.
- **Readest is pattern inspiration, not a fork.** The fork/clone path in
  BUILD_PLAN Phase 8 is superseded.
- **ReadAny is the UX reference** (`github.com/codedogQBY/ReadAny`, GPL-3.0):
  the patterns worth copying are the ambient chat context ("AI knows your
  position, selected text, and highlights"), the reader/chat split, and
  highlights as first-class state. Our repo is GPLv3, so its patterns are
  compatible; prefer reader-engine code from MIT sources.
- **foliate-js is the candidate rendering engine** (MIT, dependency-free ES
  modules, no build step — the engine behind ReadAny's and the Readest
  family's EPUB pane). It provides CFI locations, navigation, selection, and
  highlight APIs. Vendoring it is a small download and needs megabyte
  approval per BUILD_PLAN's budget rule.

## Locator strategy (the industry-standard split)

Do not generate EPUB CFIs in Python — the format is finicky and the renderer
can resolve addresses itself. Split the job:

- **Engine (ingest)**: store a dumb, durable selector per chunk. Today
  `doc` (the book's HTML file) is stored on all 1042 chunks; `anchor` exists
  but is empty for this book (its headings carry no ids — verified 0/1042).
  Add `exact` (first ~60 chars of the chunk) and the chunk's start offset in
  the doc. This is the W3C Web Annotation pair (TextQuoteSelector +
  TextPositionSelector); it needs no re-embedding, one metadata re-ingest.
- **Frontend (click time)**: resolve the selector to the renderer's native
  locator (CFI via foliate's search/navigation API), scroll, highlight.
  Fallback to plain text search when offsets drift.

Pattern anchors for the UX: NotebookLM, Readwise Reader — source pane +
chat pane; citation click navigates the source pane.

## Phases

- **A — the reader exists.** Vendor foliate-js into the window; engine serves
  the book's files; `[Ch. N]` becomes a link that jumps and highlights;
  a "back to the question" control. Needs: new static/read routes and `doc`
  (plus locator) fields on citations.
- **B — durable locators.** Ingest stores `exact` + offset; highlights are
  exact even when the same words repeat in the book.
- **C — frontend as product.** Highlights, notes, reader state in chat
  context (the ReadAny ambient pattern), TTS/sync only if ever wanted.

## Open decision (the user's)

Single-file vanilla window + vendored foliate-js (fits the repo's "no build
step" rule; recommended first), or a React/Vite frontend like ReadAny's
stack (needs an explicit exception to that rule). The API stays the same
either way; a React shell later is a swap of the shell, not of the engine.

## Contract changes this plan needs (explicit yes required)

- New routes for book files/assets (the four-route freeze).
- Citation objects gain `doc` (and in Phase B, `exact`/offset). Additive,
  but still a contract change.

## Facts this plan is built on (measured 2026-10-13)

- 1042 chunks, all with `doc`; 0 with a non-empty `anchor`.
- 17 book documents in the index (`OEBPS/ch01.html` …).
- The book's XHTML carries ids (178 in ch01 alone — footnotes, note refs),
  so heading-level ids may exist elsewhere or can be injected at serve time.
- Window today: 90 lines, vanilla JS, one `fetch("/ask")`, no libraries.
