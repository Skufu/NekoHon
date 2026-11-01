# Handoff — LFM3 base swap and teacher upgrade

Date: 2026-10-30. For: the next agent picking this up cold.
Status: **nothing trained, nothing downloaded, no repo code changed.** Two plan
files exist and one hardware measurement was made.

Read this file top to bottom before touching anything. It carries the whole
context, including the traps, so the next session does not redo the research or
repeat a mistake.

## The decision rule (owner, 2026-10-30)

> Use the current model, or the teacher model — as long as that teacher model
> is better than the student, use the teacher.

Read as: **no swap and no retrain on vibes.** A teacher or a new base is
adopted only when it beats the shipped student on the repo's own gates, on the
same questions, same evidence, same quantisation, same runtime. Otherwise the
current model stays (`nekohon_q35_2b_x3_2e`).

## Work order (owner decision, 2026-10-30)

1. Repair the finetuning dataset first (`plans/data-quality-and-retraining-2026-10-29.md`).
2. Retrain the **current** base on the repaired corpus, benchmark it.
3. Test **stock LFM3, no training**, benchmark it.
4. Train LFM3 on the **same** repaired corpus, benchmark it.

One factor per arm, or nothing can be attributed:

| # | Arm | Changes | Isolates | Cost |
| --- | --- | --- | --- | --- |
| 1 | shipped `nekohon_q35_2b_x3_2e` | — | reference | free, already measured |
| 2 | Qwen3.5-2B on the repaired corpus | data | did the data repair help | 1 Colab run |
| 3 | `lfm3:1.7b`, stock | base | the base's floor; can it hold our format at all | free, 1 download |
| 4 | LFM3-1.7B SFT on the same repaired corpus | base, data held | is the base better at equal data | 1 Colab run |

Arm 3 gates arm 4: if stock LFM3 cannot hold the answer format, the SFT has to
teach everything and the run gets expensive. Do not skip arm 3.

**Do not start arms 2 or 4 on the current 777-row derivative.** It still
shares a same-question, same-source DataOps item with the new dev set. A base
swap measured on a leaky split cannot be told from luck.

## Established facts — do not re-research

### LFM3 (checked 2026-10-30)

| Item | Value |
| --- | --- |
| Repos | `LiquidAI/LFM3-1.7B` (post-trained), `LFM3-1.7B-Base` (pre-trained), `LFM3-1.7B-GGUF` |
| Size / shape | 1.73B, 24 layers (13 gated short conv, 5 sliding-window attn, 6 global attn), 128K vocab, 256K context |
| GGUF | Q4_K_M 1.10 GB, Q5_K_M 1.26, Q6_K 1.43, Q8_0 1.85, F16 3.47 |
| License | LFM Open License v1.0 — commercial use permitted under USD 10M annual revenue; redistribution must carry the license and a modification notice (matters: `nekohon_*` is public on HF) |
| Finetune route | TRL SFT + LoRA only. Notebook: `finetuning/notebooks/lfm3_sft_with_trl.ipynb` in `Liquid4All/cookbook` |
| LoRA targets | `q_proj k_proj v_proj o_proj in_proj out_proj w1 w2 w3` (+ optional `gate_proj`). A Llama/Qwen target list trains ~nothing |
| Thinking | on by default. Must set `enable_thinking=False` at training **and** at generation. The engine already sends `"think": False` (`answer.py:744`, `:799`) |
| Tooling gaps | `LiquidAI/liquid-finetune` (LEAP) is LFM2-only. **No Unsloth LFM3 repos exist** — the Unsloth notebooks used for `nekohon_x3` cannot be reused |
| GGUF export | llama.cpp PR #31252 merged 2026-10-27, so build at or after that commit |
| Ollama floor | v0.40.12 (2026-10-27, Apple silicon), v0.40.13 (2026-10-28, Linux/Windows). `ollama run lfm3:1.7b` exists in the library |

Known upstream bug that does not affect us: llama.cpp #31328, `response_format`
/ `json_schema` fails on LFM3. The engine never uses structured outputs.

### Colab hardware — measured, not assumed

A self-cleaning `colab run --gpu A100` probe on 2026-10-30 returned:

| | |
| --- | --- |
| GPU | **NVIDIA A100-SXM4-40GB — 40,960 MiB VRAM** |
| Host RAM | 83 GB |
| Disk `/content` | 206.8 GB free |
| Python / torch | 3.13.16 / 2.11.0+cu130, cuda True |
| llama.cpp | **not installed** (cmake present) |
| Balance | 152.23 compute units, ~6.7 units/hour |

**The card is 40 GB, not 80 GB.** "High-RAM" in Colab is host memory, not VRAM.
There is no CLI flag for an 80 GB card on this account and `H100` is
ineligible. Consequence: the teacher runs at Q4–Q6, so a bigger challenger has
to be quantised harder than the 27B incumbent — the size win is partly paid
for in quantisation. That is why one arm below is a quant control, not a new
model.

Budget: five teacher arms at roughly 1 hour each is about 27 of the 152 units.
`colab` v0.7.5 is installed at `~/.local/bin/colab` and already authenticated
as `adrian0123francisco1@gmail.com`. Always `colab stop -s <name>`; never leave
`--keep` sessions behind.

### Teacher candidates for a 40 GB card

The teacher's entire job is: pick the answering sentence, copy it **verbatim**,
gloss in one or two sentences without adding a fact, refuse with exactly
`Not in this book.` when it is absent. Nothing in that job rewards general
capability, and published agentic benchmarks are **not** selection evidence.

| Model | License | Quant that fits | Note |
| --- | --- | --- | --- |
| `Qwen/Qwen3.8-27B` | Qwen | UD-Q4_K_XL 17.6 GB (incumbent) / UD-Q6_K 22.0 GB (control) | current teacher |
| `Nanbeige/Nanbeige4.3-33B` | Apache-2.0 | Q5_K_M 24.7 GB (Q6_K 30.1 and Q8 35.2 do **not** fit) | explicitly released as a distillation teacher, 512K ctx, thinking on by default |
| `google/gemma-4-31B-it` | Apache-2.0 | Q4_K_M 18.3 GB / Q6_K 25.2 GB | strongest prose and instruction lineage |
| `meta-models/Muse-Glimmer-30B` | Apache-2.0 | UD-Q6_K_XL 26.3 GB / Q8_0 29.6 GB | agentic tool-use focus |

Selection method: the behavioral pre-gate already inside
`reports/teacher-capture-colab-2026-10-15.ipynb` (9 probe items + 5 capture
rows, hard stops on thinking leaks, empty replies, cap-hits), same rows and
same serving settings per arm (`-c 16384 --parallel 4 --cache-reuse 256`, max
250 generated tokens).

Promotion rule, fixed before the runs: a teacher wins only on captured-row
quality — verbatim quote rate, refusal correctness on out-of-book rows, zero
thinking leaks, zero cap-hits, and a gloss that introduces no new fact.
Training loss and public benchmarks do not count.

### Ruled out, with reasons

- **Underdog-Saluki-27B, Swift-1.5-Qwen3.8-27B, every `Qwen3.8-27B-GSQ-RCO`
  build** — these are **quantizations of the incumbent**, not upgrades. They
  have millions of downloads and read exactly like upgrades.
- **DeepSeek-V4.1-Flash-1017** — GGUF is IQ2 sharded at ~40 GB per shard,
  ~160 GB total. Does not fit 40 GB VRAM or 83 GB host RAM. Also the family
  the eval judge runs on; teacher and judge from one model share blind spots.
- **flint (40B / A2.5B)** — agentic coding (SWE-bench, Terminal-Bench). Wrong
  job, and its active budget goes to tool syntax.
- **Ling-3.1-flash, Hy-Memory-30B-A3B** — footprint unverified. Revisit only if
  all four arms above disappoint.

## How to run each arm

**Upgrade Ollama first (arm 3 cannot run otherwise).** This Mac is on 0.40.2,
the Windows box on 0.40.3; both are below the 0.40.12 floor.

```bash
brew upgrade ollama            # or the official installer
ollama --version               # must report >= 0.40.13
ollama pull lfm3:1.7b         # 1.1 GB, stock, no training
ollama ps                      # confirm what is actually loaded
```

**Swap a model into the engine** (never edit `prompt.py` to test):

```bash
ANSWER_MODEL=lfm3:1.7b python server.py
```

Restart the engine after **any** `*.py` edit or `ANSWER_MODEL` change, and
verify with `/api/ps` that the expected model is loaded. A running server keeps
the code and model it loaded at start — this is a recorded, measured trap in
this repo. Keep exactly one listener on `:8000`.

**Gates** (the numbers that decide adoption):

```bash
python -m unittest discover -s tests                 # must stay green
python preflight.py                                  # readiness, read-only
python verify_index.py                               # index hygiene

python artifacts/harnesses/run-gate.py --smoke --model <tag>          # quick
python artifacts/harnesses/run-gate.py --model <tag> --label <name>   # full

python artifacts/harnesses/step2-battery.py          # server must be up; ask mode
BATTERY_MODE=answer python artifacts/harnesses/step2-battery.py
python artifacts/harnesses/sealed-eval.py <model>    # 30 items, in-process
python artifacts/harnesses/hard-mt-eval.py <model>   # 12 items
python artifacts/harnesses/adrian-eval.py            # 35 scenarios
```

Current shipped numbers to beat or tie: battery 22/22, hard bench 59–60/60,
sealed 27/30, adrian 32/35, highlight golden 24/24, exact refusals, 0 loops.

**Colab:**

```bash
colab run --gpu A100 job.py          # provisions, runs, tears down (self-cleaning)
colab new -s <name> --gpu A100       # or a persistent session...
colab exec -s <name> -f job.py
colab stop -s <name>                 # ...always stop it
colab usage                          # free, allocates nothing
```

llama.cpp is not preinstalled on the VM; the capture kit builds it.

## Hard rules that will bite

- **Local runtime only.** In-process or `127.0.0.1:11434`, engine on `:8000`.
  Zero cloud runtime calls. The one exception is the eval judge
  (`opencode/deepseek-v4.1-flash-free`, fallback `opencode-go/deepseek-v4.1-flash`),
  evaluation only — never the engine.
- **One factor at a time.** Do not swap teacher *and* base model in one run.
- **Do not tune a constant until a gate passes.** A constant is fitted if its
  stated reason is which known test it keeps green.
- **No chunk ids, figure ids, chapter numbers, query strings, or book ids in
  the logic modules.** `tests/test_generalization.py` enforces the literal part.
- **Reserved/locked cases stay sealed.** Do not inspect them to author training
  examples or pick checkpoints (`data-quality-and-retraining-2026-10-29.md`,
  work order 4 and 5). Never run `fair-eval.py --split locked` while iterating.
- **Never call the 7B "the teacher"** without "original" — it is the original
  teacher only.
- **Do not commit unless the owner asks.**
- **A plausible example is not evidence.** Open the source and check it before
  repeating a quote, a count, or a benchmark claim.

## Machine gotchas on this box

- This Mac's `ollama list` has only `nekohon_q35_2b_x3_2e`, `nomic-embed-text`,
  `deepseek-r1:7b`, `qwen2.5:7b`, `llama3.2:3b`. The revert seams quoted in
  `AGENTS.md` (`ANSWER_MODEL=nekohon_x3`, `=nekohon_q35_2b`) **do not exist
  here** — those tags live on the Windows box. Pull what you need before using
  a revert seam.
- `AGENTS.md` "Machine facts" describes a Windows box with many more tags; this
  session is macOS. Do not trust the tag inventory in that section for this
  machine — run `ollama list`.
- The working tree has uncommitted owner work in `fts_index.py`, `fusion.py`,
  `artifacts/harnesses/dataset_integrity.py`, `reviewed_eval.py`,
  `web/app/api/`, and the data-quality tests. Do not revert or overwrite it.

## What "done" looks like

- Dataset repaired, splits frozen, retrain packaged and measured (arm 2).
- Stock LFM3 measured on the battery and the hard bench (arm 3), with a written
  verdict on whether it can hold the format.
- If arm 3 is viable: LFM3 SFT on the same corpus, Q4_K_M (and Q5_K_M as the
  quant fallback), then the full gate list (arm 4).
- A dated verdict report under `artifacts/reports/`, the plan updated, and
  `python artifacts/prune.py --plan` clean for whatever was promoted.
- Adoption only if it beats or ties the shipped student on the gates. Losing
  and saying so is a finished result; a non-adoption is not a failure.

## Pointers

- `artifacts/plans/lfm3-base-candidate-2026-10-30.md` — LFM3 facts, SFT recipe,
  runtime floor, the four-arm table.
- `artifacts/plans/teacher-upgrade-2026-10-30.md` — hardware measurement,
  teacher arms, exclusions, promotion rule.
- `artifacts/plans/data-quality-and-retraining-2026-10-29.md` — the dataset
  work that gates arms 2 and 4.
- `artifacts/reports/teacher-capture-colab-2026-10-15.ipynb` and
  `artifacts/reports/colab-capture-session-2026-10-15.md` — the existing
  teacher capture kit and its runbook.
- `AGENTS.md` — constitution, hard rules, current state, verify commands.
- `GOAL.md` — the goal and constitution, the only layer that blocks work.

## Open decisions

1. Which teacher arm to run first (suggest the cheapest informative one: the
   incumbent at UD-Q6_K, the quant control).
2. Start LFM3 SFT from the **post-trained** checkpoint (recommended: 777 rows
   teach a format and a refusal, not a language) or from `-Base` (only if the
   repaired corpus grows a lot).
3. Colab unit budget for the five teacher arms (~27 of 152 units).
