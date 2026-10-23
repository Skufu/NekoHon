# Pane now

What the reader, library and margin cards do today, and the file for each
behavior. Read before touching them. The code is the authority; if this page
and the code disagree, fix this page.

## What the reader sees

- **Library start menu** (`web/components/library/`): opens on launch or from the
  top bar's library button. Shelf view and grid view (`Shelf.tsx`, `Grid.tsx`),
  per-book cards (`BookCard.tsx`), a detail spread with a begin-reading action
  (`BookDetail.tsx`), and EPUB drag-and-drop import (`ImportDrop.tsx`, which
  posts `mode: "import"`). Only books the engine has indexed are listed. Per-book
  state is isolated in localStorage (`nekohon-state-<book_id>`,
  `nekohon-progress`).
- **Three-column reader** (`.reader-grid` in `web/app/globals.css`), default theme
  `night`:
  1. Left rail (from 1260 px, `reader/Rail.tsx`): chapter ticks, highlight bars,
     gloss dots, a draggable viewport thumb.
  2. Center prose (`reader/Reader.tsx`): one block per chunk (`data-chunk-id`),
     inline figures with reserved aspect ratio, four user highlight colors,
     gloss anchors, and a cite mark with an animated underline on citation jump.
     Selection offsets, word-boundary snap, heading and caption selection and
     cross-chunk selection live in `lib/anchor.ts`. Off-screen chunks use
     `content-visibility: auto`.
  3. Right margin (from 1080 px, `margin/Margin.tsx`): cards placed beside their
     anchored passage by a collision solver (`GAP = 16`, `GAP_MINI = 6`,
     `CROWD = 88`); crowded or inactive cards collapse to single-line pills; an
     SVG leader curve joins the active card to its anchor. Below 1080 px the
     active card is a bottom sheet.
- **Margin cards** (`margin/MarginCard.tsx`, `TurnView.tsx`, `FollowUpForm.tsx`,
  `CardActions.tsx`, `useDragResize.ts`): header drag, two widths, resize,
  minimize to a pill, stacked turns with a follow-up input and suggestion chips,
  and a figure already shown in an earlier turn is not repeated. Quiz cards anchor to the active chunk
  and reveal the key sentence on demand.
- **Selection lens** (`reader/Lens.tsx`): select text to get Explain, Ask, Copy and
  four highlighter colors; typing a printable key starts an ask.
- **Composer** (`reader/Composer.tsx`): whole-book question box (`/` focuses it)
  with a bounded suggestion popover, an Answer / Quote first toggle and a Quiz
  trigger.
- **Top bar** (`reader/TopBar.tsx`): tucks on scroll down, reveals on scroll up;
  book switcher, library button, chapter menu, running header, progress line,
  and the appearance menu (5 themes, 4 pens, text size 15 to 26 px).
- **Answers** (`reader/AnswerView.tsx`): gloss first, then the italic quote with a
  clickable chapter chip; `Read as:` / `Asked as:` disclosures; the exact
  `Not in this book.` refusal with `nearest misses:`; refusal figures labeled
  `nearby, not an answer`.

## Where the code is

| Behavior | File |
| --- | --- |
| Library, import | `web/components/library/`, `engine/server.py` (`import` mode), `data/books.json` |
| Reader blocks, citation scroll and mark | `web/components/reader/Reader.tsx`, `web/lib/quote.ts` |
| Selection offsets and heading offsets | `web/lib/anchor.ts` |
| Margin layout and cards | `web/components/margin/` |
| Cards, turns, token pacing, in-flight streams | `web/lib/store.ts`, `web/lib/stream.ts`, `web/lib/turns.ts` |
| Per-book persistence | `web/lib/persist.ts` |
| Themes, pens, text size | `web/lib/appearance.ts`, `web/app/tokens.css` |
| Intent classification and follow-up chips | `engine/answering/intent.py` |
| Gloss guard and fallback | `engine/answering/gloss.py` |
| Reader payload (gzip, cached) | `engine/server.py` (`/chunks`), `engine/retrieval/retrieve.py` |

## Conversation

Open [conversation-map.md](conversation-map.md) before changing history. A card
sends its last 2 completed turns as `history`.

## How to check

1. `python3 -m unittest discover -s tests`
2. `cd web && npx tsc --noEmit && npm run build`
3. `python3 artifacts/prune.py --plan` (0 unindexed, 0 missing)
4. With the engine and Ollama up: `python3 artifacts/harnesses/step2-battery.py`
   and `BATTERY_MODE=answer python3 artifacts/harnesses/step2-battery.py`
5. Open `http://localhost:3100` (dev) or `http://127.0.0.1:8000` (built): open a
   book, select a sentence, Explain, click the citation chip, reload and confirm
   the highlight persists.
