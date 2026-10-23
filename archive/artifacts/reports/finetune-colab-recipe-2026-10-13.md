# Teach the small model — Colab recipe, plain steps (2026-10-13)

You need: Colab Pro, two files — `data/finetune/quote-refuse-2026-10-13.train-x2c.jsonl`
(167 cards) and `data/finetune/quote-refuse-2026-10-13.train-x2.jsonl`
(167 cards) — and this notebook: `finetune-colab-2026-10-13.ipynb`.
Total time: ~60-90 minutes, most of it waiting (two trainings, one session).

What training does in one sentence: we show the GPU your ~150 solved cards
~6 times; it nudges a small model's behavior toward "quote this, gloss
like this, refuse like this" — without retraining the model from scratch
(that is what "LoRA" means: a small patch, not a new brain).

## v5 update (2026-10-14) — the current session

Trains two candidates in one session, same Qwen2.5-3B base:
- Slot A: `train-x2c.jsonl` (167 cards, seed 3407) -> `smallbook_x2c_gguf.zip`
  (q4_k_m) and `smallbook_x2c_q8_gguf.zip` (q8_0);
- Slot B: `train-x2.jsonl` (167 cards, seed 1234 — the seed control)
  -> `smallbook_x2_seed1234_gguf.zip` (q4_k_m only).

Upload **BOTH** files when the picker opens:
`quote-refuse-2026-10-13.train-x2c.jsonl` and
`quote-refuse-2026-10-13.train-x2.jsonl` — not the bench file (the exam
stays here).

The notebook pins the toolchain that trained x2 (`unsloth==2026.10.5`,
`transformers==5.17.0`; a fallback to latest keeps the session alive if a
pin is unavailable), prints the versions actually loaded, asserts each
run loaded its expected 167 cards — once after `load_dataset` and again
after responses-only prep, the truncation canary — and gives each run
its own seed (A 3407, B 1234). The q8_0 export on Slot A is the quant
A/B from the pre-registered gate (`x2-trial-2026-10-14.md`, item 5): the
x2c warts must persist at q8_0 — a wart that vanishes there is a
quantization verdict, not a training verdict. A q8 failure prints a
WARNING and does not kill the session.

Watch two lines in every run's output:
- **"Num examples"** (trainer banner) — must read **167** for both runs;
  the assert stops a run whose rows were silently dropped;
- **STOP-CHECK** — one quote + one gloss line, then silence. A LONG
  OUTPUT verdict means tell me before trusting that zip.

## v4 update (2026-10-13 night) — superseded by v5

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
refusals; v4's x2 won the ratio hunt (0 loops in 168 capped draws, battery
18-19/21) and is the app's trial default, but the live trial found
refusal-margin warts on unmemorized query forms; v5 perturbs those rows
(x2c) and trains a seed control alongside.

If cell 6 (model B) fails at load: Runtime -> Restart session, re-run cells
1-4 (upload both files again), then run cell 6 alone.

## Steps

1. Open https://colab.research.google.com → New notebook.
2. **Important:** menu Runtime → Change runtime type → **A100** if offered,
   otherwise **L4** — both fine, High-RAM not needed. T4 also works but is
   much slower.
3. File → Upload notebook → pick `artifacts/finetune-colab-2026-10-13.ipynb`.
4. The cell with `RUNS` already has the two candidates (Qwen2.5-3B on the
   x2c file, then the same base on the x2 file as the seed control). If
   your search named something better, replace a model line — the cards
   do not change.
5. Run the cells top to bottom (each cell has a ▶ button):
   - install (~2 min) — pinned versions, then a one-line version print,
   - upload **both** train files when asked (x2c and x2 — do NOT upload
     the bench file; that one is the exam and stays here),
   - **cell 5**: trains run A (x2c; ~20 min on A100, ~30-45 min on L4;
     watch the loss numbers slide down), prints a STOP-CHECK line, then
     downloads its two zips (q4_k_m + q8_0),
   - **cell 6**: same for run B (x2 content, seed 1234, the seed control)
     and its q4_k_m zip, same session — both runs are the same 3B base;
     A differs by data, B differs only by seed.
6. Send me all three zips (or drop them in the repo folder yourself) and
   say "they are here".

## What I do then (nothing for you)

1. Import the zips into Ollama as `smallbook_x2c` and
   `smallbook_x2_seed1234` (my job — no commands for you), plus the q8
   build of x2c for the quant A/B.
2. Restart the engine on the candidate and run the pre-registered gate
   from `x2-trial-2026-10-14.md`: refusals 2/2 exact, the sealed fragment
   suite, the capped loop sweep, the battery at equal draw counts, the
   quant check, and a revert rehearsal.
3. x2c replaces the trial default only if the gate passes — the seed
   control tells us how much of any movement is noise. If some questions
   break, the failures name the next cards to add.

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
