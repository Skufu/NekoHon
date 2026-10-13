# Teach the small model — Colab recipe, plain steps (2026-10-13)

You need: Colab Pro, two files — `data/finetune/quote-refuse-2026-10-13.train-x2.jsonl`
(167 cards) and `data/finetune/quote-refuse-2026-10-13.train-x1.jsonl`
(140 cards) — and this notebook: `finetune-colab-2026-10-13.ipynb`.
Total time: ~60-90 minutes, most of it waiting (two trainings, one session).

What training does in one sentence: we show the GPU your ~150 solved cards
~6 times; it nudges a small model's behavior toward "quote this, gloss
like this, refuse like this" — without retraining the model from scratch
(that is what "LoRA" means: a small patch, not a new brain).

## v4 update (2026-10-13 night)

The x3 file taught refusals but made the 3B loop on some answers — loops
measured at temp 0, 0.1, 0.2, 0.3 and with penalties
(`finetune-loop-eval-2026-10-13.md`) — and the Qwen3-4B variant over-refuses
on in-book questions, so it is parked. The current notebook:
- trains **two candidates in one session**, same Qwen2.5-3B base:
  x2 (167 cards) -> `smallbook_gguf.zip`, x1 (140 cards) ->
  `smallbook_x1_gguf.zip`, to find the refusal ratio that stops the loops;
- upload **both** train files when the picker opens (multi-select);
- trains on the model's answers only (`train_on_responses_only`), 120 steps;
- prints a STOP-CHECK line after each training — one quote + one gloss
  line + silence. A "LONG OUTPUT" verdict means tell me before trusting
  that zip;
- watches the trainer banner: **"Num examples" must match the card count**
  (167 / 140). A smaller number means rows were dropped — on 2026-10-13
  night a fresh Unsloth build defaulted `max_length=1024`, cut the
  assistant marker off long rows, and silently kept 15/167; the notebook
  now passes `SFTConfig(max_length=max_seq_length)`.

History: v1 rambled forever (full-text loss). v2/v3 fixed stopping but lost
refusals; v4 narrows the refusal ratio.

If cell 5 (model B) fails at load: Runtime -> Restart session, re-run cells
1-3 (upload the file again), then run cell 5 alone.

## Steps

1. Open https://colab.research.google.com → New notebook.
2. **Important:** menu Runtime → Change runtime type → **A100** if offered,
   otherwise **L4** — both fine, High-RAM not needed. T4 also works but is
   much slower.
3. File → Upload notebook → pick `artifacts/finetune-colab-2026-10-13.ipynb`.
4. The cell with `RUNS` already has the two candidates (Qwen2.5-3B on the
   x2 file, then the same base on the x1 file). If your search named
   something better, replace a model line — the cards do not change.
5. Run the cells top to bottom (each cell has a ▶ button):
   - install (~2 min),
   - upload **both** train files when asked (x2 and x1 — do NOT upload the
     bench file; that one is the exam and stays here),
   - **cell 4**: trains run A (x2; ~20 min on A100, ~30-45 min on L4; watch
     the loss numbers slide down), prints a STOP-CHECK line, then
     downloads zip 1,
   - **cell 5**: same for run B (x1) and zip 2, same session — both runs
     are the same 3B base, only the data differs.
6. Send me both zips (or drop them in the repo folder yourself) and say
   "they are here".

## What I do then (nothing for you)

1. Import both files into Ollama as `smallbook` and `smallbook_q3` (my
   job — no commands for you).
2. Restart the engine on the small model and run the exam we already have:
   the ask battery, the answer battery, the retest corpus, class variance.
3. Compare against the recorded 7B numbers (all committed). If the small
   model passes them at a fifth of the size, the swap is earned. If some
   questions break, the failures name the next cards to add.

## If a cell turns red

Copy the red text and send it to me; notebook libraries drift, and every
fix has been quick so far. Two known ones:
- "no chat template": tell me — we add two lines to the notebook.
- model name not found: the tag was typed wrong; paste the exact tag from
  the model page or from your search notes.

## What not to expect

This makes the model good at ONE job: quoting, glossing, refusing from 5
passages. It will not become smarter about data engineering, not answer
"who is Matt Turck", and not write essays. That is the point — tiny, fast,
and honest about the book.
