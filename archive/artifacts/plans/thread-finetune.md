# Thread finetune — how, and when not to

Status: draft 2026-10-15. Do not train from this file.

The shipped student is `smallbook_x2d`. The teacher for new rows is the Qwen3.8-27B capture path (Colab, offline). The 27B is not the engine. The engine stays Ollama on localhost. Revert any trial with `ANSWER_MODEL=smallbook_x2d`.

## Do this before any train

The student was trained on one-shot rows. `user_message` now prepends `Earlier in this conversation (not a source — do not quote it):` when `history` is present (`answer.py`). That block was not in the x2d rows.

Probe first. Five follow-ups, history filled, `smallbook_x2d`, no new tag.

Done-when: each second-turn quote is inside this turn's passages, or the body is exactly `Not in this book.` If that holds, do not finetune. The wire is enough.

If the second turn quotes the previous answer, or drops the `[Ch. N]` line, that is the train.

## What to train

Keep the existing one-shot rows. Do not replace them with chat rows. A student that only sees threads forgets the one-shot contract.

Add a minority of follow-up rows. How many is **Not measured**. Enough to see the Earlier block. Not enough to drown the quote-first base.

Each follow-up row is the same prompt the server sends now:

- `SYSTEM` (quote first). Not `SYSTEM_ANSWER`.
- `user_message(question, passages, history=…)` — the Earlier block, then Question, then Passages.
- Gold is quote-first from **this turn's** passages, plus one gloss. Or exactly `Not in this book.`

Teacher writes the gold offline (27B on that same prompt, or the local 7B if the 27B is down). Then `parse_completion` keeps or drops the row. A row the parser refuses is not gold, unless the gold is the refusal sentence.

## Rows to keep

| row | what it teaches |
| --- | --- |
| "what about that" and the new passages hold the referent | quote the new passage, not the prior answer |
| "say that simpler" | one gloss, quote still from this turn's passages |
| "show me the figure" | quote the passage that names the figure; no pixel description |
| follow-up the book does not cover | exactly `Not in this book.` even though Earlier has an answer |

## Rows to drop

- Teacher copied a sentence from Earlier that is not in this turn's passages.
- Teacher essay with no quote.
- Sealed-suite prompts. Never trained.
- History used as if it were a passage (`Passages:` must stay this turn only).

## What not to finetune

- The 27B as the serving model. It is the teacher.
- The embedder.
- `agentic.py`. Thread is not a tool loop.
- A new prompt shape. Train the shape `user_message` already builds.

## Sequence

1. Probe x2d. If it holds, stop.
2. Capture 27B on the live `user_message` with history. Offline. Not `server.py`.
3. Filter with `parse_completion`. Mix a minority into the existing one-shot set.
4. SFT a new Ollama tag. Do not point the default at it.
5. Gate: battery, pins, sealed suite, plus the five follow-ups from step 1. Adopt only if both hold.

Revert at every step: discard the new rows or `ANSWER_MODEL=smallbook_x2d` and restart the engine.

The one-shot recipe stays in `distill-small-model.md`. This file only adds the thread slice.
