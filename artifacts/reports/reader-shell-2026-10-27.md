# Reader shell: five prototypes, Nightfall chosen (2026-10-27, finished 2026-10-28)

The frontend needed a shell that a book reader would actually use — a library
that shows covers, and a reading page with one column. Five prototypes were
built as standalone HTML fixtures in `artifacts/scratch/`, reviewed, and one was
wired into `web/` as **Nightfall**. The engine, `/ask`, citations, highlights,
glosses, themes, pens, and the 503-test suite are unchanged.

## The five

| Direction | Idea | Outcome |
| --- | --- | --- |
| `reading-experience-2026-10-27-room.html` | Reading room: warm paper, shelf planks, bookplate details | Rejected — the metaphor outgrew the reading page; plank/wood chrome competes with the prose |
| `-index.html` | Index: dense typographic catalogue, sortable rows, table-of-contents energy | Rejected — good for finding a book, cold for opening one; covers become thumbnails |
| `-margin.html` | Margin: the Gloss three-column shell (rail, prose, margin cards) | Rejected — the shipped shell already did this; the task was to leave it behind |
| `-poche.html` | Poche: pocket-book proportions, very small format, compact chrome | Rejected — the page reads as a phone UI on desktop and shrinks the measure too far |
| `-nightfall.html` | **Nightfall**: dark cover wall, one amber hairline, 66ch column, focus dimming, amber progress, bottom sheet | **Chosen** |

Prototype index and the content fixture live in `artifacts/scratch/`
(`reading-experience-2026-10-27.html`, `reader-flow-content-2026-10-27.json`).
Scratch is unindexed by rule; nothing was promoted.

## What Nightfall is

- **Library.** Logo + wordmark, a 38px amber rule, "The shelf at night.", a
  one-line lede, a 3-up cover wall (286px covers, 2:3), then title / author /
  chapter-and-passage meta and an amber reading dot. Search on `/`, import on a
  solid amber button, whole-window drag-and-drop. Below 760px the wall becomes a
  70vw snap carousel and the header stacks.
- **Reader.** 64px topbar: Nekohon mark, centred volume switcher, Contents,
  Focus (`aria-pressed`), notes count, `Aa`. A 2px amber progress hairline sits
  above the bar. The prose is a single 66ch column at `--read-size` (19px
  default) with `line-height: 1.72`.
- **Focus.** On by default. Every paragraph is `--focus-dim` (ink 62% / bg);
  the paragraph nearest 42% of the viewport gets `.is-lit` and full ink. Escape
  closes a gloss first, then a highlight, then leaves focus. The topbar's own
  Escape handler closes its menus first and stops the event.
- **Answers.** From 1080px, a 320px card in the reserved right margin beside
  the quoted passage: draggable by its header, resizable, with a 28px SVG
  leader line across the gutter and the collision solver for multiple notes.
  Below 1080px the same card uses `.gloss-sheet`: 760px centred, 16px above the
  bottom, max 64dvh; full-width, bottom-anchored, 74dvh, 14px top radius on
  phones. The composer is hidden while the sheet is open (`:has(.gloss-sheet)`).
  The sheet's dismiss is a 40px close at the sheet's top left, above the card;
  the card's own X deletes the note.

## Files

- `web/app/nightfall.css` — new; the whole shell layer, imported after
  `globals.css` in `app/layout.tsx`.
- `web/app/tokens.css` — `--danger` per theme, `--danger-soft`,
  `--nf-amber-hover`, `--nf-cover-shadow(-hover)`; `--nf-amber` moved into each
  theme block so night/ink get `#d6a548` instead of the light `#9a6f1c`
  (the late `:root` declaration was winning on equal specificity).
- `web/components/LibraryView.tsx` — rewritten as the shelf; props are
  `{ loadError }`.
- `web/components/TopBar.tsx` — new props (`bookTitle`, `activeChapter`,
  `chapters`, `onJumpChunk`, `focusMode`, `onToggleFocus`); menu Escape handler.
- `web/components/Reader.tsx` — no rail, no margin column; `focusMode` state,
  reading-line lighting, amber progress, sheet rendering.
- `web/app/layout.tsx` — title "Nekohon — Local Book Companion", mark favicon,
  Nightfall import.
- `web/public/nekohon-mark.svg` — the supplied mark, recreated as SVG.
- `web/README.md`, `.agents/skills/book-companion-ui/SKILL.md` — describe the
  single-column + sheet shell now.

## Verified (2026-10-28, measured)

Environment: engine `server.py` on `:8000` (`nekohon_q35_2b_x3_2e`, warm in
6.434s), static export on `:3200` built with `NEXT_PUBLIC_ENGINE_URL=http://127.0.0.1:8000`,
Chrome via `puppeteer-core` at 1440×900 and 390×844 (DPR 2).

| Check | Measured |
| --- | --- |
| `python -m unittest discover -s tests` | **503 tests OK** in 151.133s |
| `npm run build` | clean (TypeScript + static export) |
| Library at 1440 | 4 books, 4/4 covers loaded from `/figures/cover`, cover box 286×429, 3 columns `329.3px ×3`, `scrollWidth == innerWidth == 1440` |
| Shelf title / logo | "The shelf at night.", mark 44px in the library and 28px in the topbar |
| Search | "quant" → 1 match; "zzzz" → empty state with the query echoed in curly quotes |
| Import error | `.nk-import-line.is-error`, "Choose an .epub file to add it to Nekohon.", danger colour `rgb(235, 143, 120)` |
| Reader at 1440 | topbar 64px, title 54px, prose 627px (66ch) at 19px, exactly **1** `.chunk-p.is-lit`, progress `rgb(214, 165, 72)`, no horizontal overflow |
| Contents | 17 items, opens right-aligned, no overlap after the label/heading stack |
| `Aa` | 287px wide, 5 themes + 4 pens + 15–26px size |
| Escape with a menu open | both menus close, `data-focus` stays `"true"` |
| Focus toggle | off → `data-focus="false"`, on → `"true"` |
| Paper theme | bg `rgb(246, 243, 236)`, accent `rgb(154, 111, 28)`, title `rgb(29, 27, 24)` |
| Gloss sheet at 1440 | 760×408 at x=340, bottom 884, radius 14px, close 40×40, composer opacity 0 |
| Gloss sheet at 390 | 390×493 at x=0, bottom 0, top radius 14px, close 40×40, no horizontal overflow |
| Mobile reader | topbar 64px, brand name hidden, Focus label shown, prose 350px, 1 lit paragraph |
| Console | 0 errors across the runs |

Screenshots: `artifacts/scratch/screenshots/nightfall-2026-10-28/`
(`library-1440`, `library-390`, `reader-top-1440`, `reader-1440`,
`reader-contents-1440`, `reader-aa-1440`, `reader-1440-paper`,
`library-import-error-1440`, `reader-sheet-1440`, `reader-sheet-390`,
`reader-top-390`, `reader-topbar-1440`, `library-header-1440`).

## Not measured

- Safari, Firefox, iOS or Android hardware. Chrome desktop emulation only.
- Real `prefers-reduced-motion` at the OS level (the CSS path exists and was
  read, not toggled).
- Screen-reader traversal, axe/Lighthouse, or computed contrast ratios.
- 320px width and long-title truncation below 390px.
- Focus-mode timing/jank on a real 1042-chunk book beyond the scroll check.
- `/ask` latency; the sheet check used a real Explain turn but did not time it.

## Follow-up (2026-10-28): the margin card returned

The owner asked for the older form when highlighting: the answer as a movable
mini card at the side, with a leader line. Ported from `HEAD`'s Gloss shell
without reviving the rail: `Reader.tsx` watches
`matchMedia("(min-width: 1080px)")` and mounts `<Margin wide />` inside
`.reader-grid` on wide screens, or the sheet outside the grid below it.
`nightfall.css` reserves the 320px column (`read-size × 33` prose + 28px gutter
+ 320px) so the prose never shifts when a note opens.

Measured at 1440 (quantization, a body paragraph):

| Check | Measured |
| --- | --- |
| Grid | `627px 320px`, prose x=233, margin x=888, gutter 28px |
| Card | 320×411 at x=888, active, not mini |
| Leader line | `.gloss-leader` present, SVG 28px wide |
| Sheet | absent |
| Header drag | card y 333 → 413 (+80px) |
| 1000px viewport | no `.rg-margin`; sheet 760×408 at x=120 |
| Console | 0 errors |

Screenshots: `reader-margin-empty-1440.png`, `reader-margin-1440.png`,
`reader-margin-dragged-1440.png`, `reader-sheet-1000.png`.

## Follow-ups

- `web/components/Rail.tsx` is no longer imported. Kept for reference; delete
  in a dedicated cleanup commit if nothing needs it.
- The margin column is reserved on every wide screen, so the prose sits left of
  the viewport centre even with no notes. This is deliberate (no shift when a
  note opens); revisit if the empty hint feels too heavy.
- The `.gloss-sheet` dismiss sits at the top left because the card's top-right
  X deletes the note. If the card ever gets a separate close, move the sheet
  dismiss back to the conventional right.
- The 4th book in the shelf leaves a hole in the 3-column grid. Acceptable at
  four volumes; revisit if the catalogue grows past nine.
