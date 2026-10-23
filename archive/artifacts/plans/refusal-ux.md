# Refusal UX — not cold, still honest

Date: 2026-10-15. Design only. No source edited. `GOAL.md` not edited.

The sentence stays `Not in this book.` Period included. Nothing else in the `answer` field. Warmth goes in the chrome around that sentence, built from passages the engine already returned.

## What the book says today

Constitution, `GOAL.md` line 37: **Refusal is exactly** `Not in this book.`

The goal section also says a later turn may follow the last one, and a refusal is still only that sentence. `GLOSSARY.md`: the sentence means "the book does not cover this" — never "I didn't understand you."

`prompt.py` holds `REFUSAL = "Not in this book."` `answer.py` `_refusal` returns that string, up to three nearest-miss citations (quote clipped), and any figures those passages name, with `refused: true`. An empty retrieval is the same sentence with an empty citation list.

The window and the Next pane already do some chrome:

- the sentence is not red, not an icon, not an error
- chips are prefixed `nearest misses:`
- figures are prefixed `nearby, not an answer`
- engine-down is a different string (`Could not reach the engine.` on the window; `Engine unreachable — start it on :8000, then ask again.` on the Next pane)
- the screen reader announcement is the sentence itself (`AskPane.tsx`)

What the reader does not get: a line that says why this happened, a quote they can read without opening a chip tooltip, or a button for the next move.

## Why the bare sentence fails a reader

This is a reading of the contract plus the two surfaces above. Not a study. No reader counts. Not measured.

**Dead end.** The sentence answers "is it in the book?" and then stops. Nielsen Norman (fetched 2026-10-15, *Error-Message Guidelines*): stating the problem is not enough; offer a remedy and a way to recover without starting over. Apple HIG Writing (fetched, `writing.md`): an empty or stuck screen should name the next action, and a button or link should do it. A refusal is not an error (the UI skill says so), but the same gap applies. The reader has nowhere to go except retype.

**No next action.** The misses exist. On the Next pane they are chips whose quote is a `title` tooltip, clipped. On the window they are chunk ids (`ch05-019`), which are not a page a person can open. The figure note says "nearby, not an answer" and does not say "open this page."

**Sounds like the app broke.** One short sentence in the answer slot, after a long `Looking…`, reads like a crash message or a stub. Apple HIG Alerts (fetched, `alerts.md`): a title that does not say what happened ("Error") fails; say what happened and in what context. The bare sentence does not say "we looked" or "these pages were the closest." A false refusal (the book does have it; the check failed) makes this worse. Copy cannot make a false refusal true. `reader-failure-moments.md` rank 4 already names that path.

**Three different failures, one voice if you are not careful.** Today the engine already splits two of them. The third is not a product state.

| What happened | What the reader should hear | What the code does now |
| --- | --- | --- |
| Book does not cover it | the exact sentence, then the closest pages, labelled as not the answer | `refused: true`, `answer` is the sentence |
| Engine down, bad JSON, stream drop | what failed, what to start, then stop | a different string; never the refusal sentence |
| Question had no content ("what is", spaces) | do not pretend this is "not in the book" | not shipped. Whitespace and thin prompts can still retrieve and quote (`reader-failure-moments.md` rank 9). A refusal string here would be a lie. |

Gemini Notebook help (fetched 2026-10-15, support article 16164461, product renamed from NotebookLM on that page) lists three reasons an answer can fail: a safety flag, unclear phrasing, and "information not in sources." That split is the useful idea. Do not import the safety bucket. This app has no safety-flag state. Do not tell the reader to "rephrase" as if their wording were the fault. The glossary forbids that reading. Unclear phrasing, when it is real, is the unshipped empty-question case, or a `Read as:` repair the app already discloses. It is not a softer refusal sentence.

Perplexity: the citations blog returned a Cloudflare block (fetched 2026-10-15). A different Perplexity page (Publishers' Program, same day) says they cite sources so the reader can check. That is the pattern already in this app. Their "I don't know" screen was not fetched. Training knowledge, not a measurement: consumer answer engines often fill the gap with a guess plus a hedge. That pattern is the anti-pattern below. Do not copy it.

## Patterns that keep honesty

All of these use fields the body already has, or a mode the engine already has. None of them add a fact.

**Nearest passage, shown, not hinted.** When `refused` and `citations` is non-empty, show the miss quote in the pane, under a label that cannot be read as a citation. The label already exists: `nearest misses:`. Prefer the quote over the chunk id. The quote is passage text, clipped at `MISS_QUOTE_CHARS`. Say the clip is a clip if it ends mid-sentence. Do not ask the model to write a better snippet.

**"Closest I found" means not the answer.** One fixed line, UI-owned, not model-owned: "Closest I found. Not the answer." Then the quote. Apple: informative text only if it adds something the title did not. This line adds the status the sentence does not carry. It must stay visually smaller than the sentence, same rule as the UI skill.

**Show the page anyway.** A chip or a "Show this page" control jumps the reader pane to that chunk and highlights the quote string, same jump as a real citation. The label on the control is the difference. `ux-possibilities.md` already says a miss must not look like a citation, and a not-found citation (sentence missing from the chapter text) must not share this voice. Do not highlight a nearby sentence to be helpful if the quote is not in the loaded chunk. Say the chapter number instead.

**Suggest a better question only from the book.** The model must not invent a follow-up. A safe suggestion is mechanical: the heading line of the nearest miss, or the first sentence of that passage, offered as "Ask about: {heading}". The heading is book text. If the miss has no heading, offer nothing. An empty retrieval offers nothing. Do not generate "you might have meant…" from the model. That is a second answer, uncited.

**"Ask about this selection" / "Ask about this passage".** Explain mode already treats a selection as the question. A button that sends the nearest passage's text as `selection` in explain mode asks the book to explain a span that exists. It does not claim the original question was answered. Say that on the button: "Explain this page" not "Try this instead" (the second sounds like the app is correcting the reader). Known limit, already written in `reader-failure-moments.md` rank 11: the typed lens path does not send `selection`. This button only works on the path that does. Do not ship the label on the path that ignores the passage.

**Engine-down stays a different state.** Keep the current split. Refusal: no red, the sentence, misses subordinate. Error: plain failure, name the thing to start (`:8000` / Ollama), no refusal sentence, no filled-in answer. Do not put both in the same live-region string. A spinner, a "Looking…", or a token stream must end in one of those two states, never in a blank `<pre>` (`body.answer || body.error || ""` can still land empty on the window).

**Do not invent a fourth voice for false refusal.** If the check failed and the book does contain the answer, the honest UI is still the refusal plus the misses, until the check is fixed. A softer sentence would hide the bug. Rank 4 in `reader-failure-moments.md` is a contract or model change, not a copy change.

## What must stay machine-exact

The split: engine `answer` stays the sentence; the pane adds chrome. That split is safe for the battery. It is not a license to rewrite the sentence in the JSON.

Why the tests hold, if and only if `body.answer` is unchanged:

- `tests/test_contract.py` pins `prompt.REFUSAL` to `Not in this book.` and requires that string inside `SYSTEM` and `SYSTEM_ANSWER`.
- `tests/test_answer.py` `test_refusal_must_be_exact` and the failed-quote cases require `body["answer"] == REFUSAL`. An essay after the sentence is parsed back down to the sentence. A short overlap, an invented quote, and a gloss-only completion are refusals with that answer.
- `tests/test_canonical.py` asserts the answer is the sentence and that `Asked as:` is not folded into it.

If you change the string itself — drop the period, add a second sentence, let the model keep talking in `answer` — those asserts fail, the prompt contract fails, and the sealed battery's refusal rows fail. In ask mode a line that starts with the sentence and then continues is already defined as not a clean refusal (`AGENTS.md`). In answer mode the first line must be the sentence or it is not a refusal.

Screen readers today announce the sentence (`AskPane.tsx`). Chrome can add a second announcement ("Closest page is chapter N") without replacing that one. Replacing it would make the spoken answer disagree with the contract. Do not do that.

`GOAL.md` still says the refusal is only that sentence, including on a later turn. This plan does not edit that line. A wrap that puts extra words into `answer` would need a constitution change. A wrap that leaves `answer` alone and renders labels, quotes, and buttons beside it does not. The UI skill's "no apology copy, no invented elaboration" still applies to model text. Fixed UI labels are not model elaboration. They are also not a second answer.

Empty citations: chrome that needs a passage must hide itself. The sentence stands alone. That is the honest shape when retrieval found nothing.

## Three presentations

Ranked for a reader who asked a real question and got a true refusal. Same engine body in all three.

### 1. Sentence, then the closest page, then one verb (ship this)

What the user reads:

> Not in this book.
>
> Closest I found. Not the answer.
>
> “{quote from citations[0], book text, clipped}”
>
> [Show this page] [Explain this page]

What the engine still returns: `answer` exactly `Not in this book.`, `refused: true`, citations as today.

What test breaks if you change the string itself: `test_the_refusal_sentence_is_exact`, `test_refusal_must_be_exact`, every assert that `body["answer"] == REFUSAL`, the prompt fixtures, the sealed refusal rows. The buttons and the "Closest I found" line are not in `answer`, so they break none of those if the renderer only paints them when `refused` is true.

Why first: one next action, the page is checkable, the miss cannot be mistaken for a citation, the sentence remains the thing a test and a screen reader can match.

### 2. Sentence plus the miss quote, no new verb (smaller)

What the user reads:

> Not in this book.
>
> nearest misses: “{quote}” · Ch. {n}

The chip still jumps, as it does now. No "Explain this page" button.

What the engine still returns: the same body.

What test breaks if you change the string itself: the same set as option 1.

Why second: this is mostly the Next pane today, except the quote is visible instead of a tooltip, and the window stops showing raw chunk ids. Less to build. Weaker next step. A reader who does not know a chip is clickable still sees a dead end. Acceptable as the first slice of option 1 if the buttons slip.

### 3. Hide the sentence; show a warmer line (do not ship)

What the user reads:

> This book doesn't cover that. Here is the closest page.

The JSON still has `answer: "Not in this book."` The pane never shows it.

What the engine still returns: the sentence, unseen.

What test breaks if you change the string itself: the same engine tests. UI tests and the live region would also rot, because they look for the sentence on screen (`ux-possibilities.md`: the live region says `Not in this book.`).

Why last: warmest, and dishonest about the contract the reader was promised on the empty state ("the answer is 'Not in this book.'"). A person who copies the answer, or who hears a different line than the one in the JSON, cannot check the product against itself. Shipping this needs a `GOAL.md` change this plan is not allowed to make. Do not do it as "just UI."

## Anti-patterns

**Fake apology essays.** "I'm sorry, I wasn't able to find that in the materials provided, but I'd be happy to help with something else." Apple HIG Writing: interjections like "oops" sound insincere; do not blame the reader; do not add words that do not help. NN/g: avoid humor on a message people will see often. An essay also breaks the exact-string tests the moment it lands in `answer`.

**"As an AI".** Names a narrator the product does not have. The book is the source. The sentence is the refusal. Apple: avoid "we" when it is unclear who failed. "As an AI" is that failure, plus a disclaimer. It does not tell the reader whether the page exists.

**Invent an answer, then cite.** A fluent paragraph with a chip on a nearby page is the failure mode `reader-failure-moments.md` ranks above a cold refusal (ranks 3 and 5: uncited prose kept, invented gloss that still looks grounded). A refusal the reader can check beats a helpful lie. Do not let a model write "you might have meant" and attach the nearest chunk. That is the same lie in a shorter coat.

**Hide the refusal behind a spinner.** `Looking…` until `final` is already a ranked failure (rank 1). A refusal must not add another hold, a second generation, or a paraphrase pass to "make it nicer." The plain-register rewrite path already holds tokens; do not run it on a refusal. `_plain_body` already keeps a draft refusal as the refusal. The pane should leave the wait state on `refused` the same way it leaves it on `done`. A spinner that never resolves, or a stream of apology tokens that `final` then deletes, reads as a crash. Show the sentence as soon as the body says `refused`.

**Do not dress engine-down as the sentence.** Already the rule. Restated because a friendlier refusal makes the temptation worse. If Ollama is down, "Not in this book." is false.

## Out of scope

- Changing `GOAL.md`, `prompt.REFUSAL`, or the parser.
- A model-written softening line.
- Fixing false refusals (rank 4) or empty-question retrieval (rank 9). Those are contract or model work. This page only says: do not paper over them with warmer copy.
- A safety-flag state. This app does not have one.

## Sources

Fetched 2026-10-15:

- Apple HIG Writing, markdown: https://developer.apple.com/design/human-interface-guidelines/writing.md — clear next step on an empty screen; error text names the fix; no "oops"; no blame.
- Apple HIG Alerts, markdown: https://developer.apple.com/design/human-interface-guidelines/alerts.md — say what happened; do not interrupt with an alert that only informs; button titles are verbs.
- Nielsen Norman Group, *Error-Message Guidelines* (Neusesser and Sunwall, 2023-05-14): https://www.nngroup.com/articles/error-message-guidelines/ — visible, human, constructive, preserve the user's effort. A refusal is not an error in this app; the recovery rule still fits.
- Gemini Notebook help, "Learn why Gemini Notebook is unable to answer your questions": https://support.google.com/notebooklm/answer/16164461 — three distinct reasons (safety, unclear phrasing, not in the sources). Use the split, not their safety bucket.

Not fetched, so not used as evidence:

- Perplexity citations post: Cloudflare block. The Publishers' Program page was fetched and only supports "cite so the reader can check," which this app already does.
- Any "I don't know" UX study, click-through rate, or preference score: Not measured.

Repo lines this plan treats as measured by reading, not by a user test: `GOAL.md` refusal line, `answer.py` `_refusal`, `window/index.html` miss prefix and engine-down strings, `web/components/AskPane.tsx` live region, `artifacts/plans/ux-possibilities.md` state table, `artifacts/plans/reader-failure-moments.md` ranks 1, 4, 6, 9.
