# All user-facing frictions — 2026-10-15

One table. Rank of the top 10 is **assumed** unless a cell says **measured**. App not run this pass. Quote-span labels and window hang-forever were checked in code because older docs disagree; the 2026-10-15 UI pass already fixed the hang and most labels.

How to read the rank: a normal reader hits it and thinks the app is dumb.

| rank | friction | what the user feels | where (file) | already documented? | fix class | blocks companion? |
| --- | --- | --- | --- | --- | --- | --- |
| 1 assumed (hold **measured**) | Long `Looking…` with no tokens | Default Ask sits on `Looking… N s` until the whole body lands. After 8 s it mentions a ~25 s cold load. Nothing types. | `server.py` `_stream_ask` (`live` false for `answer`/`quiz` without prefill); `web/components/AskPane.tsx` | yes — `reader-failure-moments.md` #1; `companion-track.md` step 2; `ux-possibilities.md` states | contract | yes |
| 2 assumed | Exact refusal `Not in this book.` with no next step | The book says no. Period. No “ask it another way”, no jump to a nearby page, no simpler rephrase. Nearest-miss chips are easy to miss. | `answer.py` `_refusal`; `prompt.py` `REFUSAL`; `web/components/AskPane.tsx` | yes — `GOAL.md`; `ux-possibilities.md` states; `follow-up-history.md` | copy | yes |
| 3 assumed (ceiling **measured** on probes) | False refusal — book has it, model says no | They ask something on the page. Same exact sentence comes back. Looks like a liar, not a gate. | `answer.py` `ask` / `parse_completion`; gloss-first and short-quote fail the gate | yes — `reader-failure-moments.md` #4; `companion-track.md`; user-query probes | model (ceiling forms); contract (gloss-first / short quote) | yes |
| 4 assumed | No follow-up / thread thrown away | “Why?” / “simpler” / “and the figure?” starts a new search. Last answer is wiped the instant they Ask. | `web/lib/store.ts` `begin` (`body: null`); `answer.py` one-shot; `server.py` no `history` | yes — `follow-up-history.md`; `ux-possibilities.md`; `companion-track.md` | contract | yes |
| 5 assumed | Invented wording still looks grounded | Fluent prose, chips maybe present, `refused: false`. Sentences the page never said. Follow-up treats the gloss as fact. | `answer.py` `parse_answered` (zero-overlap stays uncited); `web/lib/answer.ts` `splitAnswer` can lead with unchecked gloss | yes — `reader-failure-moments.md` #5 | contract; model | yes |
| 6 assumed | Tag-first answer, empty chips (or silent redo) | Quote-shaped text, no chips — or the text vanishes under “Re-checking the quote…”. | `answer.py` `_sentence_claims` (cites text *before* `[Ch.`); `_retry_uncited` | yes — `reader-failure-moments.md` #2; `companion-track.md` step 2 | contract | yes |
| 7 assumed | Retry fails — uncited prose kept | A real-looking answer with no usable chips. Looks like the book spoke. It didn’t bind a passage. | `answer.py` `_retry_uncited` returns `None`; `respond` keeps the draft | yes — `reader-failure-moments.md` #3 | contract | yes |
| 8 assumed | Lens typed ask drops the selection | Pill says ask about *this* passage. Typed Enter sends only the question. Answer can drift. Empty Enter does send the passage. | `web/lib/store.ts` `askSelection`; `web/components/Lens.tsx`; `server.py` `ask` ignores `selection` | yes — `ui-review.md` mismatch #2; `ux-possibilities.md` move 3 | contract (or copy, if the pill stops implying the span) | yes |
| 9 assumed | Two homepages | `:8000` is the old form. `:3100` is the reader. Editing one does not change the other. | `server.py` `GET /` → `window/index.html`; `web/app/page.tsx` | yes — `ui-review.md`; `ux-possibilities.md` | UI | no |
| 10 assumed | Engine down and “not in this book” share a voice | Window dumps both into the same `<pre>`. Next puts the error in the same `.answer` class as a gloss. `/health` is never called. | `window/index.html`; `web/components/AskPane.tsx`; `web/app/page.tsx` loadError | yes — `ux-possibilities.md` states; `ui-review.md` #9 | copy; UI | no |
| — | No history | One slot. Reload or next Ask clears it. Composer does not reprint “you asked”. | `web/lib/store.ts`; `web/components/AskPane.tsx` | yes — `follow-up-history.md`; `ux-possibilities.md` | UI; contract | yes |
| — | Quiz key / modes missing from Next | Next composer is Answer / Quote first. No quiz, no explain in the select. Window has quiz + “Show the key”. Window quiz is a random chunk, not this page. | `web/components/AskPane.tsx`; `window/index.html`; `answer.py` `quiz` | yes — `ui-review.md` #11; `ux-possibilities.md` | UI (surface); contract (quiz-this-page) | no |
| — | Figure not attaching | “Explain figure 4.4” refuses (`4.4` ≠ book `4-4`). Tables (`Table N`) never attach. “What’s in the figure” is another retrieval, not a jump. | `figures.py` `FIGURE_RE`; `canonical.py`; reader chunk vs `figures_for` | yes — `figure-understanding-plan-2026-10-15.md`; `ux-possibilities.md`; `reader-failure-moments.md` out-of-twelve | contract | no |
| — | Window long silent wait (not hung forever) | `Looking...` with no timer, no tokens, until one JSON body. Empty `answer` and no `error` still lands blank. Network/JSON throws are mapped now. | `window/index.html` (non-stream `POST /ask`) | yes — `reader-failure-moments.md` #7 (hang-forever is **stale** vs current file) | contract (stream); copy (empty body) | no |
| — | Sidebar closed mid-ask — Stop gone | Toggle unmounts the pane. Request keeps running. Stream invisible unless a margin card is up. Second Ask no-ops with no line. | `web/app/page.tsx`; `web/lib/store.ts` `controller` / `begin` | yes — `reader-failure-moments.md` #10; `ux-possibilities.md` move 8 | contract | yes |
| — | Degenerate input gets a quote | `what is`, whitespace, `hey` can come back as a grounded passage. Owner: WRONG. Confuses what the refusal sentence means. | `server.py` `do_POST`; `answer.py` `respond`/`ask` | yes — `reader-failure-moments.md` #9 (**measured** on probes) | contract | no |
| — | Plain-words ask feels frozen longer | Cue list fires extra rewrite calls, all held from the stream. “Say that simpler” is **not** a cue — it is a new search. | `answer.py` `SIMPLE_CUES` / `_plain_body` | yes — `reader-failure-moments.md` #8; `ux-possibilities.md` | contract | yes |
| — | Citation chips / layout don’t match the words | Verbatim block instead of gloss-first; chips jump to overlap, not the on-screen span. Quote click can miss once. | `web/lib/answer.ts` `splitAnswer`; `web/components/Reader.tsx` `content-visibility` | yes — `reader-failure-moments.md` #12; `ui-review.md` | contract | no |
| — | Quote span / labels | **Mostly fixed this UI pass.** Quote is a `<button type="button">`. Ask textarea has `aria-label`. Window fields have wrapping `<label>`. Leftover: quote button has `title`, no `aria-label`; live region still does not speak Looking. | `web/components/AnswerView.tsx`; `web/components/AskPane.tsx`; `window/index.html` | yes — `ui-review.md` (those three items **stale** vs current files) | UI | no |
| — | Stuck Looking on window forever | **Not still true.** `try/catch` + non-JSON + status mapping are in the file. Remaining wait is the non-stream hold above. | `window/index.html` | yes — `ui-review.md` (stale); `reader-failure-moments.md` #7 (corrected) | — | no |
| — | Catch path leaves partial stream | `onError` clears `streamText`. The unreachable `.catch` does not. Rare half-state if tokens already arrived. | `web/lib/store.ts` | yes — `reader-failure-moments.md` #6 | contract | no |
| — | Answer figure has no size | Answer images can jump the column on load. Reader figures send PNG width/height; `figures_for` does not. | `figures.py` `figures_for`; `web/components/AnswerView.tsx` | yes — `ui-review.md` #7; `ux-possibilities.md` | contract | no |
| — | Under 900px, no jump to composer | Book stacks above a long ask pane. Resize handle hides. No skip to the box. | `web/app/globals.css`; `web/app/pane.css` | yes — `ui-review.md`; `ux-possibilities.md` | UI | no |
| — | “The other one” is not a choice | A kept swap is `Read as:`. A tie is dropped. Two chapters that share a token are not offered. | `readings.py`; `web/lib/answer.ts` disclosures | yes — `ux-possibilities.md` move 5 | contract | yes |

## Five to fix before any distillation

Held Looking. The default pane is blank until `final`. Distill rows captured from that path teach a body, not a turn the reader can watch.

Tag-first empty chips. `_sentence_claims` only cites text before `[Ch.`. A quote-first student looks uncited, then the silent retry may or may not save it. Do not train on the uncited draft.

Uncited prose kept when the retry fails. That body is `refused: false` with no bound passage. A student that copies it will look fluent and be unbound.

False refusal. Book has the page; the sentence is still `Not in this book.` Distill rows of that shape teach the student to refuse honest questions.

Invented gloss that still looks grounded. Unchecked lines ride beside a real quote. Follow-up and later training both treat them as the book.

No new product. Same ask, same refusal sentence, same one-shot engine until those five stop looking broken.

## Method

Read: `reader-failure-moments.md`, `ux-possibilities.md`, `ui-review.md`, `companion-track.md`, `follow-up-history.md`. Code checked only where those disagreed: `answer.py` refusal / `_sentence_claims` / `_retry_uncited`, `web/components/AskPane.tsx`, `window/index.html`, `server.py` `_stream_ask`, plus `web/components/AnswerView.tsx` and `web/lib/store.ts` for the UI-pass items. Not measured: a live click, timings, contrast.
