# Frontend phase 1 — engine side landed, `web/` scaffolded (2026-10-15)

Phase 1 of `artifacts/plans/frontend-build-plan-2026-10-15.md`, engine half +
scaffold. The reader and ask panes themselves are next.

## Engine (stdlib) — what landed

- **`GET /chunks`** (`server.py` + `retrieve.chunks_payload` +
  `figures.figure_cards`): the index's 1042 chunks in reading order, vectors
  stripped, the leading heading line dropped from each `text`
  (`retrieve.chunk_title` does the split; first-hand measurement: 1042/1042
  chunk texts lead with their heading), headings travel as their own field;
  figures arrive as `{id, chapter, caption, src}` cards (111 chunks carry
  one). Live: **1,187,166 bytes**, `any_embedding False`, serialized once per
  process.
- **`stream=1` on `POST /ask`** (`server.py:_stream_ask` +
  `answer.ollama_generate_stream`): NDJSON frames `token` / `reset` / `final` /
  `error`. `reset` fires before any later generation in the same ask (the
  `[Ch. ` retry, plain-register rewrites, the reading repair). The non-stream
  path is untouched. Live ("what is data engineering?", mode answer):
  **118 `token` + 1 `reset` + 1 `final`; `final.body` equal to the non-stream
  response body for the same question** (compared with `==`).
- **CORS for the dev UI**: `Access-Control-Allow-Origin` echoed for
  `http://localhost:3100` / `http://127.0.0.1:3100` only, `Vary: Origin`;
  `do_OPTIONS` answers preflight 204 (absent before — a preflight was a 501);
  `disable_nagle_algorithm` on the handler.
- Figures: unchanged — `GET /figures/{id}` already serves them (111/111 files
  present under `data/figures/`, first-hand).

## `web/` — scaffold

- Next.js 16 / React 19 / Tailwind 4 / Zustand 5; `output: "export"` (static
  export → `web/out/`, the engine serves it in production; dev on :3100).
- `npm install` (49 packages, ~1 min) and `npm run build` green; tokens copied
  from the skill's `references/tokens.css` (one comment-terminator bug fixed
  there: `--dur-*/` closed the comment early and Lightning CSS flagged it).
- Placeholder page only.

## Tests

- `python -m unittest discover -s tests`: **231 tests, OK** (was 223; +8 in
  `tests/test_reader_routes.py`: payload shape, heading strip, figure cards,
  CORS echo/deny, OPTIONS, frame order incl. reset, error frame).
- Engine restarted per the reset rule before the live checks (`/api/ps` showed
  a cold model; the first streamed ask loaded it).

## Research notes (three read-only agent audits, 2026-10-15)

**Gloss teardown** (`Nutlope/gloss`, `main @ 54b13b8`) — copy: the anchor model
`{start:{b,o}, end:{b,o}, quote}` + `spanIn`/`segments()` mark splitting (zero
offset drift); `Margin.compute`/`place` document-relative geometry (active card
pinned at its anchor, 16px gaps, mini cards when passages start within 88px,
bezier leader lines); `Cite` + `Peek` (hover preview, click-to-jump + flash,
unknown ids disabled); `Lens` ("just type" capture, docked on coarse pointers);
`ask.ts` streaming loop (TextDecoder, rAF token batching, one AbortController
per card, interrupted repair); `GlossCard` states. Skip: Clerk/quota/keys, web
search + `[1]` sources, sync/Postgres, importers, `docPayload` windowing.
Gloss uses **no Vercel AI SDK** (raw SSE from its own route handler) — our
NDJSON client is hand-rolled the same way.

**Ask-flow states + numbers** (prompt-kit / interior.dev / taste-skill): idle →
selection → composing → submitted (elapsed counter; `aria-busy`, never native
`disabled`) → first token → streaming → complete / refusal / stopped / error;
skeleton only after a 120ms delay, never shown under 380ms; caret in a
zero-width inline box; textarea autosize cap 240px; citation chips only on
`final` (a `[Ch.` token is not proof of a citation); refusal derived only from
`final.refused`; no percentage meter, no idle spinner over the ~25s cold load,
no typewriter on a frozen response. prompt-kit verdict: copy the PromptInput
pattern + stick-to-bottom behavior; skip the Radix/shadcn dependency and the
Message/Loader/shimmer set (chat chrome is banned by the project skill).
The 2026-10-12 latency numbers are stale under the repo's 2-day gate —
re-measure time-to-first-token live before hard-coding wait-state copy.

**Engine design decisions** (audit): one block per chunk (first-hand: 0 of 1025
same-doc consecutive pairs overlap — no merge needed); `chunk["anchor"]` is
empty for all 1042 → the citation jump is `chunk_id` block + verbatim-quote DOM
search (offsets later, per the navigation plan); the reader renders `heading`
only when it changes (421/1025 consecutive pairs repeat it); call the engine
directly from the browser — a Next route-handler proxy would buffer NDJSON.

## Open questions (asked of the owner 2026-10-15)

1. Components: hand-rolled (recommended) vs a shadcn/Radix base.
2. Theme scope now (paper-light) vs both themes.
3. Confirm the reader block rules above.

## Later the same day — the two panes landed

The reader + ask panes are built (`web/components/Reader.tsx`,
`web/components/AskPane.tsx`, `web/lib/{engine,store}.ts`); the app runs at
**http://localhost:3100** against the engine on :8000.

- Reader: chunks as blocks (`data-chunk-id`), `heading` rendered only when it
  changes; figures inline with the PNG's real width/height (118/118 cards
  carry them, measured; payload now 1,190,570 bytes) so nothing jumps on load.
- Ask pane: streaming text with a caret, honest wait line ("Looking… N s",
  plus the model-load note after 8 s), first-words + answered-in latency,
  Stop, and the reset explained — measured: the `[Ch. ` retry fires on
  answer-mode asks (1 reset in each of 3 live asks), so a mid-stream draft is
  replaced by design; the pane says "Re-checking the quote…" instead of
  silently blanking.
- Citations: chips from `citations[].chapter`; click → scroll to the
  `chunk_id` block and mark the quote. Search is whitespace-insensitive over
  the rendered paragraphs; the marked characters are the quote's own words.
  Checked programmatically (python replica of the matcher): 3/3 real citation
  quotes found in their blocks. Not-found and missing-block fall back to an
  honest line with the chapter number.
- Refusal/error/honesty labels kept in spirit: "nearest misses:", "nearby,
  not an answer", `Not in this book.` styled as an answer, not an error.

Measured: `npm run build` green (TypeScript clean); dev server up (Next
16.4.1, ready 691 ms); SSR shell serves 200 with reader + ask box + mode
select; streaming re-verified live (58 / 104 token frames + reset + final per
ask); `python -m unittest discover -s tests` 233 OK.

Not verified: the look. `agent-browser` does not start on this box, so no
screenshot pass was run — the owner is the first pair of eyes.

Not built yet: the Gloss margin (phase 2), the selection lens (phase 2),
explain/quiz modes (still in `window/index.html`), production serving of
`web/out` by the engine.

## Same day, second pass — one smooth stream, the lens, the margin card, the resize

**One smooth stream.** The cause was the `[Ch. ` retry: the first draft
streamed, was discarded, and
the pane wiped. Fix, engine-side: `_stream_ask` streams tokens only for the
generation whose text becomes the answer — `live = bool(prefill) or
(system == SYSTEM and mode not in ("answer", "quiz"))`; everything else is
held (`on_token=None`) and arrives via `final`. The `reset` frame stays as the
"a draft was discarded" signal and is a no-op when nothing was shown.
`ollama_generate_stream` now emits the prefill as the stream's first token
(the pane showed a bare `7]` before). Measured live after a restart:
answer `reset×1, token×45, final×1` with **first token `[Ch. `**; ask
`token×48, final×1` from frame 0; quiz `final×1` only (held). 238 tests OK
(+1: the prefill leads the token stream, transport-level). One accepted case
remains: a retry whose validation fails swaps at `final` (the draft stands).

**The lens + the margin card (Gloss's "highlight any line, ask it anything").**
`web/components/Lens.tsx` + `MarginCard.tsx` + a rewritten `Reader.tsx` and a
phase-2 CSS section: select text → an ink pill at the selection (input + Ask;
"just type"), the passage stays marked (the Gloss pending trick), a typed
question is sent as `ask`, an empty one as `explain` on the passage; the answer
streams in an anchored card beside the passage (leader line, animated in,
reduced-motion respected), only when the margin fits — otherwise the ask pane
carries it, and while the card shows, the pane says so instead of duplicating
the text.

**The resizable ask pane**: a drag handle on the divider (288–720px, clamped
to the viewport so the reader never starves, ArrowLeft/Right, double-click
resets, persisted as `ask-width`).

**A third-agent review** (read-only, fresh eyes) found six issues; all fixed:
the retry stream missing its `[Ch. ` prefix; quiz streaming a discardable
completion; the pill going stale when another ask started; the pill's position
not surviving reflow (it now follows the rendered mark + a ResizeObserver);
the pane squeezing the reader before the collapse breakpoint (viewport clamp);
and the resizer's ARIA values / `pointercancel` / duplicated answer. The
reviewer also confirmed 237 tests, tsc clean, page 200, and no token before
the first reset live.

Not verified: the look and every pointer/keyboard interaction (no browser on
this box — the owner is the first pair of eyes; a mid-edit HMR race threw once
in the open tab and self-healed with a full reload).

## Later the same day — the reader-first answer layout (owner decision 2026-10-15)

Answers now render gloss first, then the evidence quote in italics with its
`Ch. N` chip beside it; both jump to the passage and mark it. `web/lib/answer.ts`
parses the layout against `citations[]`, falling back to the verbatim answer
plus the chips row when a quote cannot be found. Streaming stays verbatim until
`final` — the reorder happens once.

Follow-up (owner feedback on the same layout): the quote renders with its
quotation marks again (`“…”` via CSS) so the model's gloss and the book's text
are never confused; with two or more citations each chip carries its index in
the engine's order (`1 · Ch. 4`); and the citation jump is now instant and
corrected over the next frames (`content-visibility` estimates off-screen
chunk heights, so one scroll could land off-target).

Polish pass (same day): the palette went cool in an intermediate edit and is
back to the warm reference (ink `#1a1a1a`, muted `#666`, rule `#e7e2d8`, the
mark an accent wash); the reader-specific tokens (wash, flash, pill, radius)
now live in both `web/app/tokens.css` and the skill's reference. Removed:
an invented bold first sentence, a hardcoded model badge, a redundant
follow-up input, an eyebrow label, a monospace chapter, a red error class,
duplicate outside-click/Escape listeners, shadows on resting controls, and
`mark` padding (it rewrapped the line). Restored click-away dismissal as a
`pointerdown` guard (`mark, .margin-card, .lens` are not "elsewhere"): the
earlier `click` handler had been removed because a drag-selection's trailing
native click killed the lens on the same frame — a `click` handler cannot be
fixed by a selection check, because the lens drops the native selection on
`pointerup`. The true margin fit check is back too. Motion added or
retuned to the reference numbers: card 180ms rise, pill 140ms scale-in, mark
flash-to-wash 420ms, the answer's 60ms-staggered settle, the sidebar toggle's
180ms column transition.

Copy pass (same day): the reader-facing strings below are gone from the Next
app. The margin header reads only `Ch. N` (no "About this
passage"); the no-question card renders the gloss alone (no "You already
selected this…" note); the fallback prints the verbatim answer (no "This
passage is the answer. Nothing was added."); the refusal shows only `Not in
this book.` plus the chips row labeled `nearest misses:` (no "Not in this
book. Closest pages are not the answer.", no "Closest I found."); the
already-selected quote collapses to its plain `Ch. N` chip; refusal figures
keep "nearby, not an answer". What the reader sees is now the engine's text
plus those two established honesty labels. Measured: 288 tests OK; `npx tsc
--noEmit` clean; `npm run build` green; `nearest misses` present and the
removed strings absent in the served bundle (`web/out`); `:3100` and `:3200`
both 200.

Deslop pass (owner decision 2026-10-15): "Answering beside the passage…" /
"Answered beside the passage." removed — the pane stays silent while the
margin card owns the answer; the "You asked:" speaker labels removed — the
question renders as plain text one tone down (`--ink-muted`); "Engine problem.
{error}" trimmed to `{error}`; "Ask again to retry." dropped from the stopped
line; the tab title is "Ask this book" (was the slug). Measured: 288 tests OK;
`tsc` clean; build green; the removed strings absent and `nearest misses` /
stopped copy present in `web/out`; both ports 200.

Note on refusal wording: `window/index.html`'s working copy (another track,
uncommitted) wraps refusals with "The check kept no quote…" + "Closest I
found."; the Next app says `nearest misses:` (matching the window at HEAD and
the skill). Align once that refusal copy settles.

Anchored-turn ownership (owner decision 2026-10-16): a highlight turn (the
lens pill, the box's Explain) is flagged `anchored` in the store and never
joins the thread; the pane's quiet gate is `anchored && marginRoom`, so the
answer no longer relocates into the pane when the card is dismissed —
dismissal dismisses it, and the pane carries the turn only when there is no
margin room. The pane's progress lines sit behind the same flag (the busy note
still shows while the card owns the turn). Anchored turns are absent from the
thread, so the (today ignored) `history` payload skips them — revisit when
history is wired. Measured: 289 tests OK; `tsc` clean; build green;
`cardVisible` gone from the bundle, `anchored`/`marginRoom` present; both
ports 200. Not measured: the no-margin fallback in a browser — no browser
automation on this box.
