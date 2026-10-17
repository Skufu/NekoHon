# Pane now — read this before touching the reader or margin cards

Status: 2026-10-17. Current reader + margin layout (Gloss port). Older notes in this folder can disagree; this page is what the code does now. Default model is `smallbook_x3` (3B desktop, 1.5B mobile).

## What the reader sees

- **Three-column Gloss layout** (`.reader-grid` in `web/app/globals.css`), defaulting to the warm-carbon `night` theme (`#151412`) and `vermilion` pen:
  1. **Left minimap rail** (`.rg-rail`, `>= 1260px`): dense paragraph ruler ticks, chapter boundaries, yellow user-highlight bars, vermilion gloss dots, and a draggable viewport thumb (`web/components/Rail.tsx`).
  2. **Center book prose** (`.rg-prose`, `--m: min(calc(var(--read-size, 19px) * 34), 46rem)`): inline figures, heading offset isolation (`renderedHeading`, `isHeadingOffset`, `decodeHeadingOffset` using negative sentinel offsets `start <= -100` preventing false highlight matches in body paragraphs), multi-layer text marks (4-color user `.hl-mark`, rubric `.gloss-anchor` underline, `mark.cite-mark` with 520ms animated rubric underline on citation jump, and revealed quiz key sentence underline), 15-character word-boundary auto-snap, cross-paragraph colon lead-in snapping, cross-chunk selection spanning across chunk and paragraph seams (`chunkId` + `endChunkId`), paragraph 2+ offset stability (`Range.comparePoint(p, 0) === 0` in `offsetInChunk`), heading/caption selection support, and viewport closest-chunk tracking (`web/components/Reader.tsx`, `web/lib/anchor.ts`). Float drop-caps and `content-visibility: auto` removed to ensure pixel-stable offsets during scrolling.
  3. **Right margin column** (`.rg-margin`, `>= 1080px`, `320px` wide, `28px` gutter): stacked `<MarginCard>` notes positioned beside their anchored passage via a two-way collision solver (`GAP = 16`, `GAP_MINI = 6`, `CROWD = 88`). Connected `Quiz` cards anchor to the active chunk, suppress duplicate `"Quiz"` labels and top blockquotes on key reveal, underline the revealed key sentence in prose, and offer quiz quick chips (`"Another quiz question"`, `"Explain the answer"`). When two notes sit within `88px` of each other, inactive notes collapse into a single-line `.is-mini` pill. Active/hovered notes draw an animated SVG cubic Bezier leader curve (`.gloss-leader`) across the gutter to the underlined passage. Below `1080px`, the active note opens in a slide-up bottom sheet (`.gloss-sheet`). 60fps token streaming pacer (`pacerTimer`, ~16ms tick) delivers smooth fluid token flow during high-speed Ollama bursts. Preemptive stream cancellation (`inFlightMap`, with `startTurnStream` excluding the active turn) cleanly terminates prior requests on re-submission or navigation.
- **Selection pill (`Lens.tsx`)**: Selecting any book passage, section heading, or caption pops up the `.lens` pill with `Explain | Ask | Copy` on the left, a divider line, and a hover-expanding 4-color highlighter drawer (`yellow`, `green`, `blue`, `pink`) on the right. Input placeholder is aligned to `"Ask about the highlighted word…"` when single terms are selected. Forwards full context (`chunk_id`, `end_chunk_id`, `selection`, `heading`) to `POST /ask`. Pressing any printable character while text is selected immediately morphs the pill into an inline question input pre-filled with that character.
- **Intent Engine & Anti-Gibberish Guard (`intent.py`, `answer.py`)**: Classifies reader selections into 4 distinct semantic classes (`CONCEPT_TERM`, `VAGUE_FRAGMENT`, `MULTI_SENTENCE_PASSAGE`, `AUTHOR_QUESTION`); `extract_core_concept` strips structural meta prefixes (`"A Brief Detour on Cloud Economics"` -> `"Cloud Economics"`); `select_substantive_anchor_sentence` anchors directly to concept definitions rather than meta lead-ins; `extract_enclosing_subject` resolves predicate fragments (`"is a perfectly reasonable strategy"`) to their full grammatical subject (`"simple lift and shift"`); `_is_coherent_gloss` rejects repetition loops, fragmentary endings, and `"sentence 0"` context recital, failing closed to `_synthesize_grounded_gloss` directly from the anchor sentence. `explain()` streams tokens live from the first model call.
- **Sticky bottom composer (`Composer.tsx`)**: Focused via `/` or `Ctrl+K`, features a bounded opaque floating popover menu (`.composer-suggestions`, max 3 filtered questions `18..62` chars) with dynamic chapter rhetorical question autocomplete for incomplete prefixes like `"what are the"`, toggles between `Answer` (`mode: "answer"`) and `Quote first` (`mode: "ask"`), triggers active-chunk connected `Quiz` (`mode: "quiz"`), and anchors whole-book questions to the current viewport paragraph.
- **Top bar (`TopBar.tsx`)**: Auto-tucks on scroll down, reveals on scroll up; includes chapter TOC selector, running header (`Preface` / `Ch. N · Heading`), notes cycler badge, progress hairline, and `Aa` appearance menu (5 themes with circular `startViewTransition` reveal, 4 rubric pens, text size 15–26px).
- **Honesty & citations (`AnswerView.tsx`, `MarginCard.tsx`)**: Gloss first, then italic quote with clickable `Ch. N` / `Preface` chip (triggering 520ms cubic-bezier smooth citation scroll and animated rubric underline on `mark.cite-mark`); `Read as:` disclosure (suppressed when `selection` or `history` is present); exact `Not in this book.` refusal with `nearest misses:`; attached figures with `nearby, not an answer`; `Show the key` toggle on quiz cards with revealed key sentence underline; dynamic follow-up suggestion chips; inline `"Ask a follow-up…"` input sending the card's last 2 turns as `history` with coreference resolution and guaranteed 1–2 sentence connected explanation gloss.

## Where the code is

| Behavior | File |
| --- | --- |
| 3-column reader, segment rendering, citation scroll, `[` / `]` shortcuts | `web/components/Reader.tsx` |
| Heading offset isolation (`renderedHeading`, negative offsets `start <= -100`) | `web/lib/anchor.ts`, `web/components/Reader.tsx` |
| Intent classification, core concept extraction, substantive anchor sentence selection | `intent.py`, `tests/test_intent.py` |
| Anti-gibberish coherence guard, grounded gloss synthesis, live first-call explain streaming | `answer.py`, `tests/test_answer.py` |
| Two-way collision solver, crowd `.is-mini` collapse, SVG Bezier leader curve | `web/components/Margin.tsx` |
| Margin card (`explain`, `ask`, `answer`, `quiz`), connected quiz UX, follow-up input, `.is-mini` pill | `web/components/MarginCard.tsx` |
| Selection pill ("peel"), 4-color swatch drawer, instant type-to-ask morph, `"Ask about the highlighted word…"` | `web/components/Lens.tsx` |
| Sticky bottom whole-book composer, bounded suggestion popover, mode chip, `Quiz` trigger | `web/components/Composer.tsx` |
| Auto-tuck header, TOC dropdown, `Aa` popover + circular view-transition theme switch | `web/components/TopBar.tsx` |
| Left minimap ruler, chapter ticks, highlight/gloss markers, scrub thumb | `web/components/Rail.tsx` |
| Quote vs gloss, refusal chips, quiz duplicate label/quote suppression, `Read as:`, figures, `formatChapter` | `web/components/AnswerView.tsx`, `web/lib/anchor.ts` |
| Plain-text offsets, paragraph 2+ `Range.comparePoint` fix, colon snap, multi-layer paragraph splitter (`splitParagraphSegments`) | `web/lib/anchor.ts` |
| Multi-card `glosses[]`, `highlights[]`, 60fps token streaming pacer (`pacerTimer`), `startTurnStream` turn isolation, `history` | `web/lib/store.ts` |
| 5 themes, 4 pens, 4 markers, animated rubric underline (`mark.cite-mark`), semantic CSS rules | `web/app/tokens.css`, `web/app/globals.css` |

## Conversation

Open `conversation-map.md` before changing history. Each `<MarginCard>` holds its own `turns[]` list; submitting `"Ask a follow-up…"` at the bottom of a card sends its last 2 completed turns as `history` on `POST /ask`.

## How to check

1. Run `python -m unittest discover -s tests` (334 tests green, 6/6 frontend rules, 3/3 generalization guards) and `npx tsc --noEmit` in `web/` (0 errors).
2. Run `python artifacts/harnesses/hard-bench.py smallbook_x3` (60/60 items passed, 100.0%, 0.92s mean latency).
3. Run `python artifacts/probes/probe-highlight-2026-10-16.py smallbook_x3` (24/24 held-out highlights passed, 100.0%).
4. Run `$env:BATTERY_MODE="answer"; python artifacts/harnesses/step2-battery.py` (battery PASS: golden 10/10, typos PASS, probes PASS, coherence PASS, France exact refusal PASS).
5. Headless Chrome verification: `node "C:\Users\ADRIAN\.gemini\config\skills\browser-recording\scripts\record.mjs" --url http://localhost:3100 --width 1440 --height 900 --scenario "C:\Users\ADRIAN\.gemini\antigravity\brain\6d166bab-6952-45e0-b2b4-1336df0e14f4\scratch\verify-intent-scroll.mjs" --out "C:\Users\ADRIAN\.gemini\antigravity\brain\6d166bab-6952-45e0-b2b4-1336df0e14f4\recordings\intent-and-scroll-verified"` (recorded all 5 user intent & smooth scroll scenes to MP4 + GIF + contact sheets).
