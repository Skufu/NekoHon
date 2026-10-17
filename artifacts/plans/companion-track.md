# Companion track

Status: steps 1–2 started in code 2026-10-15. Read this file first. Pointers, not copies.
Conversation map (history / thread / quote-check bounds): `conversation-map.md` — read before touching conversation.

`GOAL.md` now includes a later turn: simpler words, the cited passage, the figure. Refusal stays exactly `Not in this book.`

Clarify-back stays parked in `AGENTS.md` (post-v1 backlog, "Conversational companion"). That item is a third response type and a fragment-class rewrite. This track is the later turn the goal already names.

This page was written from the plan files and the named source files. The app was not run. Latency, retrieval rank, and on-screen layout are **Not measured** here.

## Live path

Each ask is one shot. `retrieve.py` `search` ranks chunks for this question. `answer.py` `ask` and `respond` send `SYSTEM` + `user_message` and check quotes against this turn's passages. `agentic.py` stays a prototype until a measured multi-hop win. Evidence for that bar: `artifacts/reports/agentic-design.md`, `artifacts/evidence/multihop/`.

`artifacts/harnesses/eval.py` and `artifacts/harnesses/groundedness.py` still default to `SYSTEM_ANSWER`. That is the meter path, not the server path. The server path is `SYSTEM` + `user_message` in `answer.py`. Pass `--system-text` on the groundedness harness to measure the live prompt. A default-harness score is not a claim about `POST /ask`.

Default answer tag is `smallbook_x2d` (`prompt.py`). Revert model for every step below: `ANSWER_MODEL=qwen2.5:7b`. Restart the engine after the env change. `ANSWER_MODEL=smallbook_x2d` restores the shipped tag without a file edit.

## Order

Do these in order. Stop when a done-when fails. The detail lives in the linked file.

### 1. One client-held follow-up that still re-retrieves — started

Detail: `follow-up-history.md` (first slice). UX rank that this step starts: move 1 in `ux-possibilities.md`.

Started in `web/lib/store.ts` (`priorQuestion`, `priorAnswer`) and `web/components/AskPane.tsx`. A short follow-up (`and `, `what about`, `say that`, `show me`, or 48 characters or fewer) is sent as the prior question plus `Follow-up:`. A longer new question is unchanged. The engine still sees one `question`. A human has not confirmed this in the reader.

Done-when: after one finished answer, a person asks again, sees the prior turn still on screen, and the new body cites a passage from this turn's retrieval (chip jumps to that chunk). An absent second turn still matches today's one-shot body.

Revert: remove the client turn. `ANSWER_MODEL=qwen2.5:7b` if a model swap was tried with it.

### 2. Fix the reader-visible failures that make a follow-up feel broken — started

Detail: `reader-failure-moments.md` ranks 1 and 2. Parser risk also named in `distill-small-model.md` and `gap-to-goal.md`.

Ship these before a second turn is treated as a companion:

- Tag-first empty citations. Started. `_sentence_claims` now treats a tag with no text before it as a claim from the quote on that line. Tests in `tests/test_answer.py`. 253 tests green (`python -m unittest discover -s tests`). A live book question was not re-run.
- Held "Looking…". The hold in `server.py` is unchanged (streaming a draft the retry may discard is the load-back-again bug). The pane now says "Checking the quote before showing it…" in answer mode instead of a bare Looking. A second click while busy sets `busyNote`. Engine errors say "Engine problem." and are not the refusal sentence.
- Refusal wrap. `answer` stays exactly `Not in this book.` Around it: "The check kept no quote" and "Closest I found" plus the miss quote. Same frame on `window/index.html`. Not confirmed in a browser.

Done-when: one in-book question in `answer` mode, saved as JSON, has a `[Ch. N]` quote that is in a shown passage and a non-empty `citations` array without relying on the retry. The pane shows words or an honest progress line before `final`. A human confirms both on the loaded tag. How often the retry saves today's drafts is **not re-measured** on this page.

Revert: restore the previous parser and stream hold. `ANSWER_MODEL=qwen2.5:7b`.

Ranks 3–5 in the same file (uncited prose kept, false refusal, invented gloss that still looks grounded) stay in that file. Fix them when they show up on the same saved JSON. They are not a new product.

### 3. Distill rows, then a small-model train only after the owner says yes

Rows: `distill-rows.md`. Steps: `distill-small-model.md`.

Row types, by name: `quote_first`, `gloss_after_quote`, `exact_refusal`, `figure_naming`, `followup_rereetrieve`, `reject_unguarded_essay` (`train: false`).

Five steps, each a tactic:

1. Lock rows to the served contract (`SYSTEM`, quote-first or exact refusal).
2. Capture teacher traces offline (local `qwen2.5:7b` or a Colab capture; not `server.py`).
3. SFT a small student as a new Ollama tag. Do not point the default at it yet.
4. Rejection-sample the student.
5. Gate (battery, pins, sealed suite), then maybe adopt.

Done-when for rows: a jsonl of those types exists, sealed prompts are absent, and every kept completion is quote-first or exactly `Not in this book.` Done-when for train: the owner has said yes, the student is a new tag, and the sealed suite plus two follow-ups in the reader are written down with command, evidence path, and before/after. Until that yes, stop after the rows.

Revert: delete the new jsonl; leave `prompt.ANSWER_MODEL` on `smallbook_x2d`. After any tag trial: `ANSWER_MODEL=qwen2.5:7b`.

## Other plans

| What | File | Use it for |
| --- | --- | --- |
| Gap vs the running app | `gap-to-goal.md` | What the code already does, and what a shortcut would break. Its "add this sentence to the goal" line is done. |
| Eight UX moves, ranked | `ux-possibilities.md` | 1 keep the note. 2 same words, plainer. 3 follow-up stays on the passage. 4 chapter and figure are places. 5 "the other one" is a choice. 6 quiz this page. 7 not-found ≠ refusal. 8 one ask at a time, visibly. |
| Conversation map | `conversation-map.md` | Read before any history/thread edit. What may change, what breaks the quote check, file map, done-when, revert. |
| Thread contract | `follow-up-history.md` | First slice vs optional `history`. Server stays stateless. |
| Failure rank | `reader-failure-moments.md` | The twelve moments. Ranks are assumed unless that file says measured. |
| Distill tactic | `distill-small-model.md` | The five steps and the revert lines. |
| Row shapes | `distill-rows.md` | Field names. Sketch only. Do not train from it. |

## Measured vs assumed

**Read, not run:** `GOAL.md` follow-up sentence; `answer.py` module docstring (`SYSTEM` + `user_message`); `eval.py` and `groundedness.py` defaults (`SYSTEM_ANSWER`); `agentic.py` unwired; first-slice shape in `follow-up-history.md`; ranks 1–2 in `reader-failure-moments.md`; five steps in `distill-small-model.md`; row type names in `distill-rows.md`; eight moves in `ux-possibilities.md`.

**Assumed:** that a client-side rewrite of "say that simpler" retrieves the same passage; that a parser fix removes the retry on common asks; any token count, latency, or suite score. Those ship with a command and an evidence path, or they stay unclaimed.
