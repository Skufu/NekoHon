# GLOSSARY — ask-this-book

Plain-language definitions for the vocabulary this repo runs on. Written for
both readers and agents. When a term's exact meaning matters, the
authoritative doc is named.

## Product

- **answer mode** — the app's default: the model writes freely from the shown
  passages; its `[Ch. N]` tags become citations; quotes the passages cannot
  back are stripped (`answer.py: respond`).
- **ask mode** — the highlight path: the model must quote one sentence
  verbatim; a failed check is a refusal (`answer.py: ask`).
- **refusal** — exactly `Not in this book.` It means "the book does not cover
  this" — never "I didn't understand you" (`GOAL.md`).
- **citation** — `[Ch. N]` plus a quote that must appear verbatim in the named
  passage.
- **passage / chunk** — one indexed piece of the book; `chunk_id` like
  `ch06-011` is chapter 6, 11th chunk.
- **pin** — the chunk id a question is expected to cite (used by the battery
  and by capture forms).
- **canonicalization** — repairing a bare user phrase into a question
  ("watermark" -> "What is watermark?"); the app shows it as `Asked as: ...`.
- **Read as:** — the app's note when what it understood differs from what was
  typed (e.g. a typo repair).
- **retry** — the engine's one `[Ch. ` prefill retry for an uncited
  answer-mode reply; kept only when a citation validates as verbatim text.
  Monotone: it can only add a citation, never change an answer.

## Models and training

- **teacher / student** — the big model that writes training answers vs the
  small model that ships.
- **distillation** — here: the teacher writes answers and the student learns
  from those answers as *text* (not from the teacher's probability
  distribution, which is why the classic capacity-gap effects mostly don't
  apply).
- **capture** — running the frozen app prompts through the teacher to produce
  training answers. **Recapture** — doing that again for the existing training
  rows with a new teacher.
- **card / form** — a training card is one (question, expected answer) pair; a
  form is one way of asking (bare, shorthand, order flip, ...).
- **expect** — per capture row: `cited` (must answer with a citation) or
  `refusal`.
- **q4 / q8** — quantization levels of the shipped GGUF (~4-bit / 8-bit
  weights). q4 is the default; q8 was measured as a wash.
- **epoch / presentations** — one epoch = one pass over the training set;
  "presentations" = rows x epochs (the budget held at ~1968).
- **LoRA** — the small trainable adapter used to finetune; the app loads the
  merged GGUF.

## Testing

- **sealed suite** — the 21 exam items (`artifacts/datasets/sealed-forms.json`)
  never trained on; near-matches abort a build.
- **gate** — the pre-registered pass/fail rules for adopting a model; **gate
  item 2** is the sealed-suite bar vs the 7B.
- **battery** — the 21 scripted app checks with pins
  (`artifacts/harnesses/step2-battery.py`).
- **loop** — a generation that stops only at the token cap, or repeats a
  5-word phrase 3+ times (`repeat5`).
- **judge** — an LLM that grades softer qualities (local granite by default;
  the cloud muse model only when explicitly enabled). Deliberately not part of
  the adoption gate.
- **owner probe / visible ten** — the user's own messy-query tests;
  exploratory, not gates.
- **contamination probe** — checks training rows against bench questions for
  near-twins.

## Repo

- **artifact** — anything under `artifacts/`: probes (scripts that run
  things), reports (the why + verdicts), evidence (raw run outputs). Index +
  rules: `artifacts/README.md`; rot check: `python artifacts/prune.py --plan`.
- **harness** — a reusable measuring tool (battery, sweeps, groundedness,
  judge, secret scan).
- **the contract** — the frozen `POST /ask` request/response shape; changing
  it needs an explicit yes.
- **engine-reset rule** — a running server serves the code and model it
  loaded at start; restart after any change and check `/api/ps`.
