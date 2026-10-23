# smallbook_x2 — model card (2026-10-14)

One page. Hash chain and toolchain: `smallbook_x2-provenance-2026-10-14.md`
("provenance" below). Scores: `smallbook_x2-scoreboard-2026-10-14.md`.

## What it is

| field | value | source |
|---|---|---|
| Type | LoRA finetune of Qwen2.5-3B-Instruct, exported as Q4_K_M GGUF | notebook RUNS; provenance |
| Base | `unsloth/Qwen2.5-3B-Instruct-bnb-4bit` | `finetune-colab-2026-10-13.ipynb` |
| Training | Unsloth, responses-only loss, 120 steps, r=16 / alpha=32, seq 4096, seed 3407; A100-40GB | notebook; provenance "Toolchain" |
| Artifact | 1,929,902,592 bytes (1.9 GB); 3.1B params; context 32768; quant Q4_K_M | provenance; `ollama show smallbook_x2` (2026-10-14) |
| Ollama tag | `smallbook_x2`, digest `ba79d37a6067` | `ollama list` (2026-10-14) |
| Status | app default on trial since 2026-10-14 (`ask` + `answer` modes) | README "Offline proof" |

## License

- Base license **Apache-2.0**. Verified on this box for the Qwen2.5 family
  via the `qwen2.5:7b` Ollama tag (Apache-2.0 text, "Copyright 2024 Alibaba
  Cloud"; `ollama show qwen2.5:7b --license`, 2026-10-14). The 3B-Instruct
  weights themselves were not re-inspected this session — treat 3B-level
  Apache-2.0 as a family-level assumption, 7B-level as verified.
- Finetune weights also carry the book-derived training text (below).

## Training-data provenance

- Teacher: `qwen2.5:7b` at temperature 0 through the shipped inference seam
  (offline localhost Ollama; system = the app's SYSTEM prompt), over
  "Fundamentals of Data Engineering" (book_id `fde`).
- Dataset: 167 train rows (113 answer / 54 refusal, refusal cards
  oversampled x2) and 45 bench rows (43 / 2, never trained); verifier PASS.
  SHA-256 chain in the provenance file.
- Contamination: 4 bench questions have near-twins in train (assisted passes;
  Codd fails anyway) — `probe-contamination-2026-10-14.log`.
- Use basis: teacher-generated Q&A with verbatim book quotes + one-line
  glosses over a copyrighted book. Personal, offline, local-use distillation;
  dataset and model are not redistributed (the `data/` path is gitignored;
  only hashes are on record).

## Measured behavior (2026-10-13/14)

- Refusal canary (France, iops): 2/2 exact.
- Loops: 0/168 capped draws across all 21 battery questions (plus 0/25
  targeted draws on the three formerly loop-prone questions).
- Ask battery (pins): 18-19/21 across the recorded passes (three surviving
  per-question recordings; see scoreboard note 2).
- Latency: ask-battery median 0.91 s / p90 1.58 s (n=63; 7B: 1.23 / 1.78).
- Trial fragments (scoreboard): 3 known warts, below.

## Known warts

- False refusals on unmemorized surface forms: Codd; CRU (lowercase);
  DE Lifecycle; Location; `ddr4 vs ddr5` order flip.
- Insert-only question cites ch08-107 on every pass (pin is ch05-020).
- Degenerate input ("what is") answers with a passage (engine guard missing).

## Serving and revert

- Already default: `python server.py` serves it. Standalone: `ollama run smallbook_x2`.
- Revert: set `ANSWER_MODEL=qwen2.5:7b` and restart the server; no code edit
  (provenance "Operational facts").
- Rebuild from scratch: `smallbook_x2-rebuild-2026-10-14.md`.

## Scope

**Not a general chatbot.** It answers only from retrieved passages of this
one book in this app's two modes, and everything else must come back as
`Not in this book.` Do not serve it for general chat, other books, or as a
public endpoint without retraining and re-evaluation.
