# Gap: the running app vs a small companion that chats inside the reader

Status: draft 2026-10-15. Written from `GOAL.md`, `AGENTS.md` "What this is", and the named source files. Not a build. No code change ships with this note.

## Aim

The aim, in the words of this request: a small local model, distilled from a stronger one, that answers like a book companion, with follow-up chat, inside the reader.

Checked against `GOAL.md`: the goal already wants an offline book companion that answers from the open book, cites the passages it used, shows the figure those passages point at, runs on weak machines with as small a footprint as we can manage, keeps nothing off the machine, and should hold for other books. Distillation and the answer model are already named as replaceable tactics, not as the goal. What the goal does not say is follow-up chat — a later turn that can refer to the last answer. That part is recorded as not approved (`AGENTS.md` post-v1 backlog, "Conversational companion", 2026-10-15). If that direction is taken up, add this sentence to the goal later; do not edit `GOAL.md` from this note:

> A later turn may follow the last one — a plain gloss, a request to show the cited passage, or a clarifying question back — and a refusal still means only that the book does not cover the thing.

Until that sentence is in `GOAL.md`, follow-up chat cannot block other work, and it is not yet the goal.

## Already true

Checked in the files named below, not taken from status prose.

- Local Ollama. `server.py` talks to `http://127.0.0.1:11434/`. `prompt.py` sets `ANSWER_MODEL` from the environment, default `smallbook_x2d`. `AGENTS.md` "What this is" says inference is local Ollama on that host. Machine-facts in the same file list the tag at 1.9 GB; that size is a doc claim, not re-measured for this note.
- Grounded quotes on the ask path. `answer.py` module docstring: ask checks the quote, and a failed check is a refusal. `parse_completion` returns a refusal for unchecked prose. Refusal text is `prompt.REFUSAL`, which is exactly `Not in this book.`
- Answer mode is not that gate. Same module docstring: answer uses the quote-first prompt the student was trained on, and the quote check "demotes from gate to meter" (`artifacts/harnesses/groundedness.py`). `respond` says "No quote enforcement." An uncited answer gets one `[Ch. ` prefill retry, kept only when a citation validates.
- Reader UI. `server.py` serves `GET /chunks` and `stream=1` on `POST /ask`. The window under `web/` has an ask pane (`AskPane`), a selection lens, and a margin card. Default mode in the pane store is `answer`. This note did not open the app.
- Two modes the reader can switch. `POST /ask` accepts `ask` and `answer` (also `explain` and `quiz`; the pane switch is the first two). `AGENTS.md` "What this is": `answer` is the window default, quote-first with `[Ch. N]`; `ask` is a checked quote plus a gloss. Since 2026-10-15 both are served `SYSTEM` + `user_message` (`answer.py` module docstring; `AGENTS.md` "What this is").
- Figures. `GET /figures/{id}` is a server route. `parse_completion` attaches a figure only when a cited passage names it. `SYSTEM` tells the model it cannot see images and that the app will show the figure.
- Finetuned tag. `prompt.py` default is `smallbook_x2d`, with the comment that it is the 1.9 GB q4 small model adopted 2026-10-14. Revert without an edit: `ANSWER_MODEL=qwen2.5:7b` or `ANSWER_MODEL=smallbook_x2`.

Retrieval constants in `retrieve.py`, for the path below: `TOP_K = 10`, `BATCH = 16`, embedder `nomic-embed-text` on `127.0.0.1:11434/api/embed`. Search is one cosine ranking of chunks. No conversation state lives there.

## Missing for the aim

- Multi-turn history. `ollama_generate` builds two messages: system, then one user turn, plus an optional assistant prefill that is the string `[Ch. `, not a prior answer. `do_POST` passes `request["question"]` only. The pane store holds one `question`, one `body`, one stream — not a thread. `web/lib/engine.ts` `askStream` payload is `{ mode, question?, selection? }`. A second ask cannot see the first.
- Distillation is not a pipeline you can run in this repo. What is in-tree: builder probes (`artifacts/probes/build-finetune-data-2026-10-13.py`, `build-finetune-x2d-2026-10-14.py`, `build-finetune-27b-2026-10-15.py`), a Colab notebook (`artifacts/reports/finetune-colab-2026-10-13.ipynb`), a teacher-capture notebook (`artifacts/reports/teacher-capture-colab-2026-10-15.ipynb`). Train rows live under gitignored `data/finetune/` (`AGENTS.md`). Training itself is a Colab session, not an engine command. `AGENTS.md` current state (doc claim, not re-run here): shipped default remains `smallbook_x2d`; an x2e student trained from a stronger teacher was gated and not adopted. Assumed from those notes, not re-checked on disk: the GGUF and the Ollama tag exist on this machine.
- Small-model behavior a companion turn would want, and does not have as a turn:
  - Plain gloss. `simple_words` fires only when the question string contains a cue (`in simple words`, `eli5`, and the rest of `SIMPLE_CUES`). `_plain_body` then rewrites draft evidence sentences one-in-one-out. A follow-up of "say that more simply" has nowhere to attach, and the cue is not "the last answer."
  - Follow-up. No prior turn is stored or sent. `canonical_query` rewrites a bare topic on the current string only.
  - "Show me that." Citation chips and the margin card can point at a chunk after an answer (`artifacts/plans/README.md` says phase 2 of the frontend landed the lens and one margin card; collision stacking was still pending in that index). There is no engine path that treats "show me that" as "open the citation from the previous body." Confirming the chip jump works is a human check in the reader, not something this note ran.
- `agentic.py` is unwired. Its module docstring: three tools, the model picks the next retrieval step, "Not wired into the server -- the four routes stay frozen." `server.py` does not import it. `do_POST` calls `ask`, `respond`, `explain`, or `quiz`.

## What must not be "fixed" as a shortcut

- Do not wire `agentic.py` into the server to get a companion feel. The docstring keeps it off the frozen routes on purpose. A tool loop is another retrieval tactic. It does not add a second turn, and it does not teach the small model to gloss or to point at the last quote. Wiring it would also spend extra local generations on every ask (the loop budget in the docstring is `max_steps` of 3).
- Do not make answer mode refuse ungrounded prose. Confirmed from `answer.py`, not from a plan: the module docstring says the quote check "demotes from gate to meter"; `respond`'s docstring says "No quote enforcement"; `parse_answered` says a hallucination is a measurement, not a refusal. Ask mode already refuses unchecked prose (`parse_completion`). Turning the meter into a gate would change the window default into the ask gate, which is a different product, and it would not create follow-up chat.

## Ordered path

Six steps. Each has a check a person can run, and a revert. No code in this note. Do not start step 2 until step 1's check is written down.

1. Measure the quote check on the model that is actually loaded, before any chat work.
   Done-when: after `artifacts/runs/start-engine.bat` is restarted, `GET http://127.0.0.1:11434/api/ps` shows `smallbook_x2d` (or whatever `ANSWER_MODEL` was set to), and one sealed-suite or battery command from `AGENTS.md` "Verify" is re-run and its citation / refusal counts are written next to the 2026-10-15 claim of 160/160 under the prompt-alignment fix. That 160/160 is a doc claim until this re-run.
   Revert: none. This step only measures. If the server was serving an old process, restarting it is the fix, and the revert is to stop that process.

2. Record one tag-first failure on the window default, in the reader's own words.
   Done-when: a person asks one in-book question in `answer` mode and one follow-up-shaped string (`say that more simply`, `show me that`) and saves the JSON body. The note to keep is whether the first answer has a `[Ch. N]` whose quote is in a shown passage, and whether the second request had any way to name the first answer (today it does not).
   Revert: none. Observation only. Do not "fix" a missing citation by flipping the pane to `ask`.

3. Keep the meter. Add a visible check the reader can do without a new mode.
   Done-when: for an answer-mode body, a person can see which sentences have a citation and which do not, using the body the server already returns (`citations` vs prose). No change to `parse_answered`'s rule that an uncited sentence stays in the answer. A human confirms one uncited sentence is still shown, not replaced by `Not in this book.`
   Revert: hide that affordance in the pane. Engine contract unchanged.

4. Single-turn "show me that" against the current body only, in the window, not a new route.
   Done-when: after one successful answer, a control in the pane scrolls the reader to `citations[0].chunk_id` (the chunks payload already has reading order). A person can do it with the mouse and the keyboard. Empty citations do nothing and do not call the model.
   Revert: remove the control. `POST /ask` request shape stays frozen.

5. Decide whether follow-up is in the goal. If yes, the owner adds the sentence above to `GOAL.md` in a separate change. Only then design the contract.
   Done-when: a written contract says what a second turn may contain (the last question, the last answer text, the last citation chunk ids — not the whole book), that `refused: true` is still only `Not in this book.`, and that "I did not understand you" is not that sentence (`AGENTS.md` backlog rule, 2026-10-15). A contract test fails if a second turn is sent and the handler ignores it, and passes when a second turn is absent (today's clients).
   Revert: leave `POST /ask` as it is. The pane keeps one question. No `GOAL.md` edit if this step is declined.

6. Distill follow-up only after steps 1–5, and only as the same tactic the repo already uses.
   Done-when: a teacher capture of multi-turn rows exists as a dated file under `data/finetune/` (gitignored) plus a verifier probe in `artifacts/probes/`, the student is a new Ollama tag (not an overwrite of `smallbook_x2d`), and the sealed suite plus a short multi-turn list are run with `ANSWER_MODEL` pointed at the new tag. Adopt only if the suite does not drop and a person accepts two follow-ups in the reader. Training stays off this machine unless an owner names a local run; the in-repo piece is the capture and the gate, matching the Colab notebooks already in `artifacts/reports/`.
   Revert: `ANSWER_MODEL=smallbook_x2d`. Delete nothing until the verdict file names what to delete.

## Risks if chat work starts while the quote check still fails on tag-first completions

`_retry_uncited` (answer.py) names the measured gap: on unseen non-canonical forms the small model writes uncited prose — it answers and drops the tag. The retry prefills `[Ch. ` so the continuation is tag-first. That continuation validates only through `parse_completion` (the ask parser). `parse_answered` / `_sentence_claims` cite text *before* a tag, so a tag-first reply cannot be trusted to the answer-mode parser alone. The retry is kept only when the quote is verbatim passage text. Every failure path returns `None` and the original uncited answer stands.

If the window grows a thread before that path is re-measured on the loaded tag:

- A follow-up is retrieved from the follow-up string alone. "Show me that" and "say that more simply" have almost no book words in them, so `search` (`TOP_K = 10`) will rank unrelated chunks. The model will then quote those chunks, or drop the tag again. The reader will see a second answer that is about the wrong passage and still looks like a companion turn.
- Tag-first text is what the retry *asks for*, and it is also the shape ask mode already requires (`Quote first. Start the quote with [Ch. N]`). A chat UI that displays the stream as it arrives will show `[Ch. ` before any gloss. Treating that as a bug and stripping the tag to "make it read like chat" removes the only marker `parse_answered` uses. The meter then cannot tell a real quote from prose, which is the failure the retry exists to catch.
- Training a chat student on those failures bakes them in. The 2026-10-15 prompt-alignment note in `answer.py` already records the matching failure mode: a student followed a prompt it was not trained on, paraphrased, and failed the verbatim check. Multi-turn rows captured from uncited or wrong-passage answers would teach that shape. The sealed suite's fragment class currently requires fragments answered (`AGENTS.md` backlog). A clarifying-question behavior would fail that class until the suite is rewritten on purpose — not as a side effect of a pane change.
- `agentic.py` does not reduce this risk. Extra retrieval steps still end in one completion with the same tag rule. More passages make a dropped tag harder to repair, not easier.

Measure step 1, then decide step 5. Do not open with a thread or with the agentic loop.
