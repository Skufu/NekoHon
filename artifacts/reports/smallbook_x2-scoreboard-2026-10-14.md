# smallbook_x2 vs qwen2.5:7b — scoreboard (2026-10-14)

All numbers below are read from the named files (or plainly derived from
them, note 1). "Not measured" where the record has nothing. Model card:
`smallbook_x2-model-card.md`; context: `x2-trial-2026-10-14.md`.

| axis | smallbook_x2 | qwen2.5:7b | source files |
|---|---|---|---|
| Ask battery, pin-pass per recorded run | 19/21 (rec 1); 18/21 (rec 2); 18/21 (rec 3, note 2) | 20/21 (preserved run); 21/21 (v3 session record) | x2: `probe-small-ask-2026-10-13.model-smallbook_x2.log` / `.run2.log` / `.run3.log`; 7B: `probe-small-ask-2026-10-13.model-qwen2.5-7b.log`; `finetune-data-prep-2026-10-13.md` (v3 table) |
| Ask battery, failing questions | insert-only wrong chunk every run (cited ch08-107; pin ch05-020); Codd false refusal every run; CRU false refusal, 2 of 3 | MAD bare form false refusal (preserved run) | same logs |
| Refusal canary (France, iops, exact sentence) | 2/2 | 2/2 | `probe-small-refuse-2026-10-13.model-smallbook_x2.log`; `probe-small-refuse-2026-10-13.model-qwen2.5-7b.log` |
| Loop sweep, 300-token cap, temp 0 | 0/168 (21 q x3 + 21 q x5); + 0/25 targeted on the three former loop questions (Codd 0/5, insert-only 0/10, source-systems 0/10) | not measured (note 4) | `probe-llm-loop-2026-10-13.x2-battery-sweep.log`; `.x2-battery-sweep5.log`; `.x2-codd.log`; `.x2-insertonly.log`; `.x2-sourcesystems.log` |
| Trial, 10 fragment/repro queries (answer mode) | refused 5/10; 3 x2-only warts — Location, DE Lifecycle, ddr4-vs-ddr5 — where the 7B answers in-book | refused 2/10 (warrup, speed of ddr5s); answers the 3 warts; stray `Not in this book.` inside the "what is" answer; meta-answers on Our Advice / speed of ddr5 | `probe-trial-queries-2026-10-14.log`; `x2-trial-2026-10-14.md` |
| Latency, ask-battery `seconds` | median 0.91 s, p90 1.58 s (n=63; min 0.45, max 7.14) | median 1.23 s, p90 1.78 s (n=21; min 0.81, max 2.72) | x2: the three `probe-small-ask-2026-10-13.model-smallbook_x2*.json`; 7B: `probe-small-ask-2026-10-13.model-qwen2.5-7b.json`; method note 3 |
| Bench, clean subset (derived, note 1) | 16/17 (rec 1); 15/17 (recs 2-3) | 16/17 (preserved run); 17/17 (v3 record) | derived from the ask-battery logs above |
| Size / quant | 1.9 GB, Q4_K_M, 3.1B params, ctx 32768 | 4.7 GB, Q4_K_M | `smallbook_x2-provenance-2026-10-14.md`; `ollama show smallbook_x2` / `ollama list` (2026-10-14); `finetune-data-prep-2026-10-13.md` |

Notes:

1. Assisted bench items — the 4 contamination twins from
   `probe-contamination-2026-10-14.log` (docs' list): data ingestion (1.00),
   enterprise architecture (1.00), pragmatic-about (0.93 / 0.89), codd
   (0.93). Their passes are assisted; Codd FAILs despite its twin. Per the
   pre-registered gate (`x2-trial-2026-10-14.md`), bench claims use the
   clean subset (21 - 4 = 17); the clean-subset cells are derived by
   removing those 4 items from the cited logs.
2. "Four passes" appears in `finetune-data-prep-2026-10-13.md` and the
   README ledger; the surviving per-question recordings are three (19, 18,
   18). The session-level `probe-small-ask-2026-10-13.{json,log}` is
   field-for-field identical to `.run3.json` (checked 2026-10-14), so it is
   counted once.
3. p90 = nearest-rank (ceil(0.9 x n)-th sorted value). `seconds` is the wall
   time of the in-process `A.ask` call — retrieval + generation
   (`probe-small-ask-2026-10-13.py`). Per-file x2 medians: 1.03 / 0.81 /
   0.81 s; rec 1's 7.14 s max is its first ask (warm-up).
4. No 7B loop-sweep file exists in `artifacts/`; the loop evidence there is
   about the smallbook checkpoints, not the 7B.
