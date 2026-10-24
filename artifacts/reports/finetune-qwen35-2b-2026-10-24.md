# Fine-tune Qwen3.5-2B — Colab steps (2026-10-24)

Same recipe as `x2f`. One base swap.

**Status 2026-10-24: executed.** Run from this machine through the Colab CLI on
an L4 (`wsl bash -lc 'colab ...'`; the bare `colab` shim exits 127). Result:
`nekohon_q35_2b`, 59/60 hard bench at 0.74–0.80s warm. Full numbers and the
head-to-head are in `artifacts/reports/qwen35-swap-2026-10-24.md` sections 6–7.
The steps below are kept as the reproducible record; step 1–4 are now historical.

## Files

- Notebook: `artifacts/reports/finetune-qwen35-2b-2026-10-24.ipynb`
- Training data: `data/finetune/quote-refuse-2026-10-16.train-x2f.jsonl` (417 rows)
- Export name: `nekohon_q35_2b`

## What is identical to x2f

| setting | value |
|---|---|
| rows | 417 (x2d + 72 highlight + refusal oversample) |
| LoRA | r=16, alpha=32, dropout 0.0 |
| targets | q/k/v/o/gate/up/down projections (see note below) |
| max seq | 4096 |
| batch | 2 x grad-accum 4 |
| lr | 2e-4, linear schedule, warmup 5 |
| epochs | `max(3, round(1968 / 417))` = 5 |
| seed | 3407 |
| loss | answers only (`train_on_responses_only`, ChatML markers) |
| checks | row count, data sha, refusal count, truncation canary, mask/EOS check, STOP-CHECK |

What differs: base model `unsloth/Qwen3.5-2B` instead of
`unsloth/Qwen2.5-3B-Instruct-bnb-4bit`.

## Steps

1. Open https://colab.research.google.com → New notebook.
2. Runtime → Change runtime type → **T4 is enough** for a 2B (16 GB). L4/A100
   are faster, not required. High-RAM not needed.
3. File → Upload notebook → pick `finetune-qwen35-2b-2026-10-24.ipynb`.
4. Run cells top to bottom.
5. When the upload picker opens, send **only**
   `quote-refuse-2026-10-16.train-x2f.jsonl`. Not the bench file.
6. Wait for `trainer.train()` (~10-20 min on T4 for 2B, 5 epochs).
7. Read the `STOP-CHECK` line before trusting anything:
   - `SANE` → zip is usable
   - `LONG OUTPUT` → stop, send me the line, do not use the zip
8. Three downloads appear: `..._q4_k_m.zip`, `..._q8_0.zip`, `..._merged.zip`.
   Put them in the repo and say they are here.

## Two things that may break, and what they mean

**LoRA targets.** Qwen3.5 is a hybrid (Gated DeltaNet + Gated Attention).
The notebook intersects the x2f target list with the modules that actually
exist and prints `lora targets: [...]`. If that prints `all-linear`, the
recipe is no longer identical to x2f — tell me before training.

**Ollama import.** Unsloth's Qwen3.5 page says: "Currently no Qwen3.5 GGUF
works in Ollama due to separate mmproj vision files." A stock
`qwen3.5:2b-q4_K_M` from the Ollama library does run here, so the arch is
supported, but a self-exported GGUF may be refused at `ollama create`.
That is why the merged 16-bit zip is exported. If the GGUF fails, we either
convert text-only or test through `llama-server` — which also means the
engine's Ollama seam needs a temporary adapter. Do not delete the merged zip.

## What I do when the zips land

1. `ollama create nekohon_q35_2b -f Modelfile` from the q4_k_m GGUF.
   If it fails, report the exact error and fall back to the merged zip.
2. Smoke test: one `/api/chat` call with `think: false`; confirm no reasoning
   block and a non-empty answer.
3. Hard Benchmark, 3 runs, `ollama stop` between runs, unloaded box.
   Control is `nekohon_x3` at 53–59/60 from 2026-10-24.
4. Adrian eval, 2 runs. Control was 30/35 and 32/35 across two runs.
5. Decision against the gate, not the average: the candidate must beat the
   control's *worst* run, not just its own best.

## Honest expectation

Zero-shot Qwen3.5-2B scored 44 and 51 of 60 against the control's 53 and 59,
and lost on injection (5/10) and multi-turn (8/10). The finetune is trying to
close a 2–9 item gap, not extend a lead. A tie at 1.9 GB would already be a
result; a win would justify the swap.

## What actually happened

| step | outcome |
|---|---|
| LoRA targets | all 7 x2f projections present, none fell back to `all-linear` |
| training | 417 rows, 5 epochs, completed |
| `STOP-CHECK` | not captured; the VM is gone, so it is unverifiable |
| GGUF export | succeeded, `Qwen3.5-2B.Q4_K_M.gguf`, 1.31 GB, text-only |
| `ollama create` | succeeded first try; runs 100% GPU |
| hard bench | 59/60 (control 59/60) |
| adrian eval | 31/35 ×3 (control 30–31) |

The predicted Ollama failure ("no Qwen3.5 GGUF works in Ollama due to separate
mmproj vision files") did not happen for a text-only export.

Two traps to remember for the next run:

1. `tokenizer("text")` raises `ValueError: Incorrect image source` — the
   processor treats a plain string as an image. Use `tokenizer.tokenizer` for
   every tokenize, mask, decode and save call.
2. `save_pretrained_gguf` writes into a **sibling** `_gguf` directory. Zipping
   the output dir captures the merged HF weights (4.5 GB), not the GGUF.
