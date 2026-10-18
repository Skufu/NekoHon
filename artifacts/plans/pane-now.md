# Pane now — read this before touching the reader or margin cards

Status: 2026-10-18. Current reader, library start menu, and margin layout in **NekoHon (`猫本`)**. Older notes in this folder can disagree; this page is what the code does now. Default answer model is `nekohon_x3` (3B desktop, 1.5B mobile) / `smallbook_x3`.

## What the reader sees

- **NekoHon (`猫本`) Library Start Menu (`web/components/LibraryView.tsx`)**:
  - Full-screen companion landing environment accessible on launch or via the TopBar Library button (`TopBar.tsx`).
  - **Shelf view**: warm walnut wooden bookcase with cloth-bound foil-stamped book spines, embossed chapter counts, and interactive hover tilt.
  - **Grid cover view**: rich card gallery featuring genuine extracted OPF cover artwork, author attributions, chunk/figure counts, and per-book reading progress indicators.
  - **3D `BookOpen` Ex Libris modal spread**: double-page parchment bookplate dialog with author bio, catalog statistics, cover thumbnail, and a direct "Begin Reading" portal.
  - **Live EPUB Drag-and-Drop Ingestion**: drop zone accepting arbitrary `.epub` files, streaming build-time ingestion via `server.py` (`mode: "import"`).
  - **Per-book localStorage isolation**: `nekohon-state-${bookId}` and `nekohon-progress` preserve distinct reading positions, user highlights, and active margin cards across catalog volumes without cross-contamination.
- **Three-book multi-volume catalog (`data/books.json`)**:
  - *Fundamentals of Data Engineering* (`fde`): 1,042 chunks, 111 figures, 17 chapters.
  - *Quantization and Fast Inference* (`quantization`): 473 chunks, 76 figures, 7 chapters.
  - *Designing Data-Intensive Applications* (`ddia`): 1,307 chunks, 90 figures, 17 chapters.
  - Corpus total: **2,822 passages**, **277 figures**, and **41 chapters**.
- **Three-column Gloss layout** (`.reader-grid` in `web/app/globals.css`), defaulting to the warm-carbon `night` theme (`#151412`) and `vermilion` pen:
  1. **Left minimap rail** (`.rg-rail`, `>= 1260px`): dense paragraph ruler ticks, chapter boundaries, yellow user-highlight bars, vermilion gloss dots, and a draggable viewport thumb (`web/components/Rail.tsx`).
  2. **Center book prose** (`.rg-prose`, `--m: min(calc(var(--read-size, 19px) * 34), 46rem)`): inline figures, heading offset isolation (`renderedHeading`, `isHeadingOffset`, `decodeHeadingOffset` using negative sentinel offsets `start <= -100` preventing false highlight matches in body paragraphs), multi-layer text marks (4-color user `.hl-mark`, rubric `.gloss-anchor` underline, `mark.cite-mark` with 520ms animated rubric underline on citation jump, and revealed quiz key sentence underline), 15-character word-boundary auto-snap, cross-paragraph colon lead-in snapping, cross-chunk selection spanning across chunk and paragraph seams (`chunkId` + `endChunkId`), paragraph 2+ offset stability (`Range.comparePoint(p, 0) === 0` in `offsetInChunk`), heading/caption selection support, and viewport closest-chunk tracking (`web/components/Reader.tsx`, `web/lib/anchor.ts`). Float drop-caps removed; CSS `content-visibility: auto` isolates offscreen chapters, collapsing layout recalculations from 1,307 down to ~6 active chunks.
  3. **Right margin column** (`.rg-margin`, `>= 1080px`, `320px` wide, `28px` gutter): stacked `<MarginCard>` notes positioned beside their anchored passage via a two-way collision solver (`GAP = 16`, `GAP_MINI = 6`, `CROWD = 88`). Connected `Quiz` cards anchor to the active chunk, suppress duplicate `"Quiz"` labels and top blockquotes on key reveal, underline the revealed key sentence in prose, and offer quiz quick chips (`"Another quiz question"`, `"Explain the answer"`). When two notes sit within `88px` of each other, inactive notes collapse into a single-line `.is-mini` pill.
- **Direct-DOM 60/120fps physics & live leader curves (`web/components/Margin.tsx`)**:
  - Live animated SVG cubic Bezier leader curve (`.gloss-leader`, `updateLeaderLineDOM`) rendered directly to DOM during window scroll and direct card drag/resize.
  - Direct pointermove transform updating bypassing React state churn for 120Hz smooth movement.
  - Figure deduplication across turns with interactive hide/show toggle button (`.figure-dedupe-toggle`).
- **Follow-up state machine & simplification fast-path (`store.ts`, `answer.py`)**:
  - Chapter-neighborhood passage prioritization prevents `"Explain more simply"` requests from jumping to unrelated chapters.
  - `SIMPLIFY_RE` fast-path extracts anchor sentences from the prior turn, reducing latency from ~2,100 ms to ~850 ms.
- **R15 engine speedups (`keywords.py`, `retrieve.py`, `readings.py`, `server.py`)**:
  - Inverted postings cache `_POSTINGS_CACHE` (82.38 ms -> 0.0018 ms, 45,000x faster).
  - Pre-normalized unit-vector dot products `_uvec` (51.69 ms -> 19.75 ms, 2.6x faster).
  - Vocabulary map cache `_SORTED_WMAP_CACHE` (19.86 ms -> 5.71 ms, 3.5x faster).
  - Gzip compressed chunk endpoint `CHUNKS_GZIP_CACHE` (1,140 KB -> 328 KB, 71.7% smaller payload).
  - Ollama persistent memory parameter `keep_alive: "24h"`.
- **Top bar (`TopBar.tsx`)**: Auto-tucks on scroll down, reveals on scroll up; includes book title switcher dropdown, library navigation button, chapter TOC selector, running header (`Preface` / `Ch. N · Heading`), notes cycler badge, progress hairline, and `Aa` appearance menu (5 themes with circular `startViewTransition` reveal, 4 rubric pens, text size 15–26px).
- **Honesty & citations (`AnswerView.tsx`, `MarginCard.tsx`)**: Gloss first, then italic quote with clickable `Ch. N` / `Preface` chip (triggering 520ms cubic-bezier smooth citation scroll and animated rubric underline on `mark.cite-mark`); `Read as:` disclosure (suppressed when `selection` or `history` is present); exact `Not in this book.` refusal with `nearest misses:`; attached figures with `nearby, not an answer`.

## Where the code is

| Behavior | File |
| --- | --- |
| 3-book Library Start Menu (Shelf view, Cover grid, 3D BookOpen Ex Libris modal, EPUB uploader) | `web/components/LibraryView.tsx` |
| Multi-book catalog metadata & spine/figure registries | `data/books.json`, `figures.py`, `server.py` |
| 3-column reader, segment rendering, citation scroll, `[` / `]` shortcuts | `web/components/Reader.tsx` |
| Heading offset isolation (`renderedHeading`, negative offsets `start <= -100`) | `web/lib/anchor.ts`, `web/components/Reader.tsx` |
| Intent classification, core concept extraction, substantive anchor sentence selection | `intent.py`, `tests/test_intent.py` |
| Anti-gibberish coherence guard, grounded gloss synthesis, live first-call explain streaming | `answer.py`, `tests/test_answer.py` |
| Direct-DOM 60/120fps physics, two-way collision solver, SVG Bezier curve, figure dedupe toggle | `web/components/Margin.tsx`, `web/components/MarginCard.tsx` |
| Selection pill ("peel"), 4-color swatch drawer, instant type-to-ask morph, `"Ask about the highlighted word…"` | `web/components/Lens.tsx` |
| Sticky bottom whole-book composer, bounded suggestion popover, mode chip, `Quiz` trigger | `web/components/Composer.tsx` |
| Auto-tuck header, multi-book switcher, TOC dropdown, `Aa` popover + circular view-transition | `web/components/TopBar.tsx` |
| Left minimap ruler, chapter ticks, highlight/gloss markers, scrub thumb | `web/components/Rail.tsx` |
| Multi-card `glosses[]`, `highlights[]`, 60fps token streaming pacer (`pacerTimer`), `startTurnStream` turn isolation, `history` | `web/lib/store.ts` |
| In-memory postings cache, unit-vector dot products, wmap cache, gzip compression | `keywords.py`, `retrieve.py`, `readings.py`, `server.py` |

## Conversation

Open `conversation-map.md` before changing history. Each `<MarginCard>` holds its own `turns[]` list; submitting `"Ask a follow-up…"` at the bottom of a card sends its last 2 completed turns as `history` on `POST /ask`. Chapter-neighborhood prioritization ensures follow-up turns stay anchored in context.

## How to check

1. Run `python -m unittest discover -s tests` (385/385 tests green across 22 test suites, clean generalization guards).
2. Run `npx tsc --noEmit` in `web/` (0 TypeScript errors).
3. Run `python artifacts/prune.py --plan` (reports `unindexed (0)` and `missing (0)`).
4. Run `python artifacts/harnesses/crossbook-evil-eval.py` (23/30 scenarios passed, 76.7% across 66 requests over `fde`, `quantization`, and `ddia`).
5. Run `python artifacts/harnesses/adrian-eval.py` (32/35 scenarios passed, 91.4% across 92 HTTP turns).
6. Run `python artifacts/harnesses/hard-bench.py nekohon_x3` (60/60 items passed, 100.0%, 0.71s mean latency).
7. Run `$env:BATTERY_MODE="answer"; python artifacts/harnesses/step2-battery.py` (battery PASS: golden 10/10, typos PASS, probes PASS, coherence PASS, France exact refusal PASS).
