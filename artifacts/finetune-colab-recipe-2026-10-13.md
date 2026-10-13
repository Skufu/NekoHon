# Teach the small model — Colab recipe, plain steps (2026-10-13)

You need: Colab Pro, the file `data/finetune/quote-refuse-2026-10-13.train.jsonl`
(126 cards), and this notebook: `finetune-colab-2026-10-13.ipynb`.
Total time: ~30-45 minutes, most of it waiting.

What training does in one sentence: we show the A100 your 126 solved cards
~3-4 times; it nudges a small model's behavior toward "quote this, gloss
like this, refuse like this" — without retraining the model from scratch
(that is what "LoRA" means: a small patch, not a new brain).

## v2 update (same day)

The first run taught the model to refuse but not to **stop** — it rambled
quote after quote forever (recorded in `finetune-data-prep-2026-10-13.md`).
The notebook now carries three fixes: it trains on the model's answers only
(`train_on_responses_only`), runs 120 steps instead of 60, and has a
stop-check cell before export.

When you re-run:
- a new cell prints a sample reply BEFORE exporting. You want: one quoted
  sentence, one gloss line, then silence. If it keeps writing, do not
  export — tell me.
- For the second candidate: change `MODEL_NAME` (try
  `unsloth/Qwen3-4B-Instruct-2507-bnb-4bit`) and `EXPORT_NAME` (e.g.
  `smallbook_q3`), then Runtime -> Restart session, and run all cells again.
  Two zips = a bake-off.

## Steps

1. Open https://colab.research.google.com → New notebook.
2. **Important:** menu Runtime → Change runtime type → select **A100 GPU**.
3. File → Upload notebook → pick `artifacts/finetune-colab-2026-10-13.ipynb`.
4. In the second cell, set `MODEL_NAME`:
   - Paste the base model your search picked. If you do not have it handy,
     the cell has a safe default; we can also swap it later — the cards do
     not change.
5. Run the cells top to bottom (each cell has a ▶ button):
   - install (~2 min), load model (~3 min), attach LoRA (fast),
   - upload the train file when the cell asks (choose the .train.jsonl —
     do NOT upload the bench file; that one is the exam and stays here),
   - train: watch the "loss" numbers in the log. Lower = less wrong. They
     should slide down over the ~60 steps.
   - export: makes a small ~2.5 GB file (Q4_K_M) and downloads a zip.
6. Send me the downloaded zip (or drop it in the repo folder yourself) and
   say "it is here".

## What I do then (nothing for you)

1. Import the file into Ollama:
   `echo FROM ./smallbook_gguf/unsloth.Q4_K_M.gguf > Modelfile` then
   `ollama create smallbook -f Modelfile`.
2. Restart the engine on the small model and run the exam we already have:
   the ask battery, the answer battery, the retest corpus, class variance.
3. Compare against the recorded 7B numbers (all committed). If the small
   model passes them at a fifth of the size, the swap is earned. If some
   questions break, the failures name the next cards to add.

## If a cell turns red

Copy the red text and send it to me; notebook libraries drift, and every
fix has been quick so far. Two known ones:
- "no chat template": the base model ships without one; the notebook has a
  comment marking where to add two lines (Unsloth `get_chat_template`).
- model name not found: the tag was typed wrong; paste the exact tag from
  the model page or from your search notes.

## What not to expect

This makes the model good at ONE job: quoting, glossing, refusing from 5
passages. It will not become smarter about data engineering, not answer
"who is Matt Turck", and not write essays. That is the point — tiny, fast,
and honest about the book.
