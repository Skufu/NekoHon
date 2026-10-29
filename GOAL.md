# GOAL — ask-this-book

The stable layer. `BUILD_PLAN.md` and the dated reports under `artifacts/` are
tactics — hypotheses that expire. This file is the only thing that rarely
changes.

## Goal

An offline book companion that answers from the open book, cites the passages
it used, and shows the figure those passages point at. It runs on weak machines
— as small a footprint as we can manage — with nothing leaving the machine.
It should hold for other books, not only this one. A later turn may follow
the last one — simpler words, the cited passage, the figure — and a refusal
is still only `Not in this book.`

**The reader is the judge.** Retrieval, models, quantization, the contract —
all means; the person asking is the end. What counts as "good" is what the
user sees: a true answer, an honest refusal, a citation they can check. An
answer that reads as broken (a false refusal, an invented fact, a recitation)
is a failure even when every mechanism underneath is green. When a trade-off
is unclear, pick the side the reader would want, then measure it.

## Constitution (non-negotiable)

Only these can block work. Nothing else in the repo can.

- **Local only.** Runtime inference and retrieval stay 100% local on the machine
  (wifi off is the proof, with zero cloud runtime calls), whether served
  in-process (`llama.cpp`, `onnxruntime`, `torch`, `sentence-transformers`) or
  via localhost (`Ollama`). One bounded exception: evaluation/judging may call a
  cloud model for testing: default `opencode/deepseek-v4.1-flash-free` since
  2026-10-29, with only `opencode-go/deepseek-v4.1-flash` as its fallback.
  `JUDGE_BACKEND=ollama` explicitly selects the offline granite judge. This is
  testing only, for
  smarter testing; the engine, server, and batteries never take this path.
- **Open local stack.** Third-party libraries (`numpy`, `sqlite3`/FTS5,
  `tokenizers`, `onnxruntime`, `sentence-transformers`, `lxml`, `PyMuPDF`,
  `usearch`/`faiss`, `llama-cpp-python`, etc.) and binary storage formats
  (SQLite, `.npy`/`.npz`, float32 blobs, GGUF, ONNX) are unrestricted. Choose
  tools by measured speed, accuracy, and footprint.
- **Grounded.** Every quoted word comes from the book's passages. Repairs move
  *which* passage text is shown; they never invent text.
- **Refusal is exactly** `Not in this book.`
- **Measured, not asserted.** A claim ships with its evidence path, its exact
  command, and its before/after numbers. The battery and the pins stay green.
  Benchmarks and tests must include negative controls (dummy, echo, or wrong-cite
  inputs must score zero) and report unvarnished pass/fail rates rather than
  engineered 100% scores.

## Tactics are replaceable

Embedder, chunking, retrieval, the answer model, a finetune, quantization, the
UI — all means, not goal. Every tactic carries a one-line revert (e.g.
`ANSWER_MODEL=qwen2.5:7b`).

When a tactic blocks the goal:

1. Change the tactic.
2. Re-run the gates (battery, pins, trial probes).
3. Update the plan in the same commit.

Do not ask permission to replace a means. Do not change a means without
re-running the gates. A dated doc is a hypothesis, not law — supersede it with
a new dated note; never edit history to fit.
