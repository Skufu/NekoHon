# LFM3-1.7B as a candidate answer-model base

Status: **candidate, not approved** (owner direction 2026-10-30). No download,
no Colab run, no model swap. The training dataset is being repaired first
(`data-quality-and-retraining-2026-10-29.md`); this track waits for that work,
then decides.

## Why it is on the list

The current default, `nekohon_q35_2b_x3_2e`, is a Qwen3.5-2B student at the
ceiling of the shipped suite (ask + answer battery 22/22, hard bench
59-60/60, sealed 27/30, adrian 32/35, highlight golden 24/24). There is no
measurable headroom left except the sealed and adrian misses, so a different
base is the only lever that changes the ceiling rather than the score.

Two properties of LFM3-1.7B point at this application specifically:

- **Instruction following.** Liquid reports IFEval 96.66, IFBench 73.03,
  IFStruct 93.72, Multi-IF 89.10. Our format enforcement has failed four
  prompt-steering attempts on the Qwen student (gloss forcing, definition
  verbs, CRU spelling note, multi-quote) — a base that holds format without
  being taught it is worth one run.
- **Admitting ignorance.** Liquid reports AA-Omniscience non-hallucination
  92.93 against 13.64 for Qwen3.5-4B. Our core product rule is a clean
  refusal, so this is the most relevant single axis a vendor reports.

Both are **vendor numbers on vendor evals, BF16, not this book**. They are a
reason to test, not evidence of improvement.

## Verified facts (checked 2026-10-30)

| Item | Value |
| --- | --- |
| Repos | `LiquidAI/LFM3-1.7B` (post-trained, created 2026-10-23), `LiquidAI/LFM3-1.7B-Base` (pre-trained, 2026-10-26), `LiquidAI/LFM3-1.7B-GGUF` |
| Parameters | 1.73B |
| Architecture | 24 layers: 13 gated short convolutions, 5 sliding-window attention, 6 global attention |
| Context | 256K tokens (input + output) |
| Vocabulary | 128,000 tokens |
| GGUF sizes | Q4_K_M 1,099,627,808 B (1.10 GB), Q5_K_M 1.26 GB, Q6_K 1.43 GB, Q8_0 1.85 GB, F16/BF16 3.47 GB |
| License | LFM Open License v1.0 |
| Ollama library | `lfm3` (1.1-1.7 GB, 256K context, tools + thinking) |

The footprint is smaller than the shipped model (1.10 GB Q4_K_M against
1.31 GB), so the ship-size promise improves rather than regresses.

### License constraint (read before publishing weights)

The LFM Open License v1.0 permits commercial use while the licensee stays
under USD 10M annual revenue, and requires that any redistribution carry the
license text, notices that files were modified, and the source attribution.
`nekohon_*` is published on Hugging Face, so **any LFM3-derived student must
ship the LFM license and a modification notice** alongside the GGUFs and
Modelfiles. Not a blocker; a packaging task.

### Finetuning path

- Official route is **TRL SFT + LoRA** (`finetuning/notebooks/lfm3_sft_with_trl.ipynb`
  in `Liquid4All/cookbook`), and that notebook is shaped like our task: train
  the cleaned answer only, in LFM3's **non-reasoning mode**.
- LFM3 LoRA targets: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `in_proj`,
  `out_proj`, `w1`, `w2`, `w3` (optionally `gate_proj`, the per-head
  attention gate). Reusing a Llama/Qwen target list trains approximately
  nothing — the documented LFM trap.
- Non-thinking mode is set with `chat_template_kwargs={"enable_thinking": False}`
  at training time and `enable_thinking=False` at generation time. Our engine
  already sends `"think": False` on `/api/chat` (`answer.py:744`, `:799`), so
  the inference half of this is already wired.
- Hardware: the notebook runs on a free T4 (fp16 fallback when bf16 is
  unavailable); A100 or L4 as used for previous runs is comfortable.
- **Tooling gaps:** `LiquidAI/liquid-finetune` (LEAP) describes itself as a
  repo "for LFM2" and is not the LFM3 route. No `unsloth/*LFM3*` repositories
  existed on 2026-10-30, so the Unsloth notebooks used for `nekohon_x3` cannot
  be reused as-is. TRL is the supported path.
- GGUF export: llama.cpp gained the architecture in PR #31252 (`model : add
  LiquidAI/LFM3-1.7B and LiquidAI/LFM3-VL-2B`, merged 2026-10-27), so convert
  and quantize from a build at or after that commit.

### Runtime requirement

Ollama added LFM3 in **v0.40.12** (2026-10-27, Apple silicon) and extended it
to Linux and Windows in **v0.40.13** (2026-10-28). The serving machines are
below that: this Mac runs 0.40.2 and the Windows box is recorded at 0.40.3 in
`AGENTS.md`. **An Ollama upgrade is a prerequisite on every machine that
serves**, and the `AGENTS.md` reset rule still applies afterwards.

Upstream defect that does not affect us: `response_format` / `json_schema`
requests fail on LFM3 (llama.cpp issue #31328). The engine never uses
structured outputs.

## What a run would cost

1. Ollama upgrade to >= 0.40.13, then a stock `lfm3:1.7b` load check
   (`/api/ps`, `think:false` behaviour at temperature 0).
2. One Colab TRL SFT job on the repaired corpus, post-trained checkpoint as
   the start — 777 rows teach a format and a refusal, not a language, so the
   base checkpoint is the wrong starting point unless the corpus grows.
3. GGUF convert + Q4_K_M (and Q5_K_M as the quant fallback; the `x2c` run
   recorded a large q4-to-q8 effect, battery 18 -> 19 and fragments 0/40 ->
   20/40, so quant is a real variable here).
4. Full gate re-run: ask + answer battery, hard bench 60, sealed 30, adrian
   35, highlight golden 24, refusal exactness, loop count, latency.

History says to expect more than one attempt: `x2c`, `x2e`, rounds 3, 4 and 5
were all trained and all not adopted for failing a single gate.

## Open questions a cheap probe answers before any training

1. Does `lfm3:1.7b` load on this box at 0.40.13+, and does `think:false`
   suppress the trace deterministically at temperature 0?
2. Does the model accept our long system prompt plus five passages without
   degenerating or drifting into a tool-call or JSON shape? (It is
   post-trained for agentic harnesses; that prior may pull against prose.)
3. What does the stock model score on the battery? It will fail — the value
   is a floor and a sense of how far the format has to be taught.
4. Does a 128K vocabulary change token costs enough to matter for the
   `num_predict: 512` cap and the 120 s timeout?

## Sequencing and the comparison design (owner direction 2026-10-30)

Owner order: repair the dataset first and run it against the benchmark, then do
LFM. Both the finetuned and the unfinetuned model get measured.

Two bases and two datasets is four cells, and only one comparison is clean at
a time. "Finetuned versus not finetuned" isolates the SFT only when the base
is held fixed — which is exactly what stock LFM3 against SFT LFM3 gives.

| # | Arm | What changes | What it isolates |
| --- | --- | --- | --- |
| 1 | shipped `nekohon_q35_2b_x3_2e` | — | reference point (already measured) |
| 2 | Qwen3.5-2B retrained on the repaired corpus | data only | whether repairing the data moved anything |
| 3 | `lfm3:1.7b`, stock, no training | base only | the base's zero-shot floor, and whether LFM3 accepts our prompt and format at all |
| 4 | LFM3-1.7B SFT on the same repaired corpus | base, with data held | whether the base is better at equal data |

Run 2, then 3, then 4. Arm 3 is free (no GPU, one download) and it gates arm 4:
if stock LFM3 cannot hold the answer format at all, the SFT has to teach
everything and the run is expensive; if it nearly holds, the SFT is cheap.

Every arm is measured on the same questions, the same evidence, the same
quantisation, and the same runtime (`data-quality-and-retraining-2026-10-29.md`,
work order 8), and failures are reported, not the best draw. The highlight
golden set (24) and the hard bench (60) are the tie-breakers: a base that wins
the HTTP battery but loses highlights is not adoptable — that was the `x2f`
precedent.

## Trigger

Start when the repaired dataset and frozen splits exist. Do not start on the
current 777-row derivative: it still shares a same-question, same-source
DataOps item with the new dev set (recorded in the data-quality plan), and a
base-model swap measured on a leaky split cannot be distinguished from luck.
