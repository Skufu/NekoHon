# Finetune data prep — quote-or-refuse dataset (2026-10-13)

Builder: `artifacts/build-finetune-data-2026-10-13.py`. Teacher qwen2.5:7b
at temperature 0, captured through the shipped inference seam
(`canonical_query` -> `retrieval_context` -> `user_message(SYSTEM)`), so
every row is exactly what the small model will see: system = the shipped
SYSTEM prompt, user = the exact user message, assistant = the target.

## Final numbers (181 questions in)

- 171 rows kept: gold 80 / silver 76 / refusal 15.
- **Split: train 126 / bench 45.**
  - Train file: `data/finetune/quote-refuse-2026-10-13.train.jsonl` — the
    only file Colab gets.
  - Bench file: `data/finetune/quote-refuse-2026-10-13.bench.jsonl` — the
    exam; never trained on.
  - Bench rule: all `eval-*` and class-variant rows, plus sweep questions
    that restate a bench topic (caught by pattern: watermark x4 incl. the
    typo, mesh; MAD deduped against the eval row).
- Refusal mining: 18 curated out-of-book candidates -> 13 refused and kept
  (train). **5 answered from passing mentions and were rejected**: install
  a Python package (preface01-006), Kubernetes (ch04-078), PyTorch
  (ch01-039), HTTP 404 (ch05-048), JVM garbage collection (ch06-051) —
  the refusal-surface weakness measured on fresh questions.
- Gloss: teacher supplied 30; 126 synthesized with `PARAPHRASE_SYSTEM`
  (the ~80% gloss-drought). Refusals are exactly `Not in this book.`
- 10 rejects total: 1 wrong-chunk, 4 teacher-refused (book-covered
  questions the ask teacher refuses), 5 answered-when-refusal-expected.
- Independent file checks: train 126 rows / 13 refusals / 0 malformed;
  bench 45 / 2 / 0.

## Schema

Row = `{"messages": [system, user, assistant], "meta": {...}}` — chat
JSONL, directly consumable by Unsloth/Axolotl/TRL `SFTTrainer`. Assistant
target is normalized: `[Ch. N] "verbatim quote"` + one gloss line.
Meta carries question/asked/source/split/tier/pin/cited/canonical_fired/
synthesized_gloss.

## Recipe

`artifacts/finetune-colab-recipe-2026-10-13.md` (plain steps) +
`artifacts/finetune-colab-2026-10-13.ipynb` (the notebook). Colab Pro /
A100; Unsloth LoRA; export a Q4_K_M GGUF; import into Ollama here and run
the bench against the recorded 7B numbers (batteries, retest, class
variance).

## First checkpoint (v1, `smallbook:latest`) — result 2026-10-13

- Colab run (Qwen2.5-3B-Instruct, 60 steps, full-text loss) -> GGUF
  **1.93 GB** Q4_K_M, imported into Ollama, runs through the real engine.
- Learned: the exact refusal sentence (France refuses correctly) and the
  `[Ch. N] "..."` shape.
- Failed: **stopping** (one call produced 174,181 chars in 354 s, quote
  after quote, never ended), wrong quote selection ("What is a watermark?"
  quoted ch06 disk blocks instead of ch08-039), and a false refusal on MAD
  (in-book question). The in-process bench (`probe-small-ask-2026-10-13.py`)
  timed out on the runaway; not runnable until stopping is fixed.
- Diagnosis: v1 trained on the whole text — the system prompt and the five
  passages sat in the loss, drowning the end-of-answer signal with 126
  worksheets of noise. Notebook v2 fixes this with
  `train_on_responses_only` (answer-only loss), 120 steps, and a
  stop-check cell before export.
- Next: v2 run, then a second candidate (change MODEL_NAME + EXPORT_NAME;
  Qwen3-4B-Instruct-2507 first, Llama-3.2-3B-Instruct optional). The v1
  checkpoint stays in Ollama as a baseline.

## Limits

- Single teacher draw (temp 0; runs deterministic, but one trajectory per
  question).
- 126 synthesized glosses carry the plain register's measured reliability,
  not a fresh audit.
- Class variants are held out entirely (bench), so surface-form training
  leans on the sweep's own style variety (bare / what-is / subject-first).
