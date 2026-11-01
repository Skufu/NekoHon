# Teacher upgrade — bake-off before the next distillation run

Status: **proposed 2026-10-30, not started.** Owner direction: a Colab GPU
session is available, so the teacher does not have to stay Qwen3.8-27B. No
model pulled, no capture run, no training.

## Hardware, measured (not assumed)

Probed 2026-10-30 with a self-cleaning `colab run --gpu A100` job (9-second
session, balance unchanged at 152.23 units):

| | |
| --- | --- |
| GPU | **NVIDIA A100-SXM4-40GB — 40,960 MiB VRAM** (40,442 MiB free) |
| Host RAM | 83 GB |
| Disk under `/content` | 206.8 GB free |
| Python / torch | 3.13.16 / 2.11.0+cu130, `cuda True` |
| llama.cpp | not installed (cmake present) |

Two corrections to the working assumption. **"High-RAM" is Colab's host-memory
shape, not VRAM** — the card is 40 GB, not 80 GB. And there is no CLI flag to
request an 80 GB card on this account (`--gpu A100` is what allocates it;
`H100` is ineligible). The plan below is sized for 40 GB, which means **Q4-Q6
quants, not Q8** — and that partly cancels the size advantage of a 33B
challenger, because it has to be quantised harder than the 27B incumbent to
fit the same card. Host RAM (83 GB) allows CPU offload beyond the VRAM
ceiling, but at four parallel slots it makes a ~500-row capture slow enough
that it is not the default.


## What the teacher is for

Build-time only; shipped models stay stock GGUF. The teacher has one narrow
job, repeated over a question plus five passages:

1. pick the passage sentence that actually answers the question,
2. copy it **verbatim**,
3. gloss it in one or two sentences without adding a fact,
4. refuse with exactly `Not in this book.` when the passages do not cover it.

Nothing in that job rewards general capability. Every candidate below is a
30B-class agentic or reasoning model, and reasoning-first priors push directly
against (2) and (4) — a model tuned to "be helpful" paraphrases, and a model
tuned to answer tries to answer.

## Incumbent and one free control

- **Qwen3.8-27B, UD-Q4_K_XL (17.6 GB)** — the 2026-10-15 capture (515 rows;
  kit `reports/teacher-capture-colab-2026-10-15.ipynb`, runbook
  `reports/colab-capture-session-2026-10-15.md`).
- **Quant control: the same model at UD-Q6_K (22.0 GB).** The repo already
  measured a large quant effect on a *student* (battery 18 -> 19, fragments
  0/40 -> 20/40), so quant has been an uncontrolled variable in every teacher
  comparison so far. Q8_0 (29.1 GB) also fits 40 GB but leaves little KV
  headroom at four parallel slots; Q6 is the honest ceiling here. If Q6
  changes the captured rows, quant was confounding the reads; if it does not,
  the next lever has to be a different model. One session, and it answers a
  question we have been guessing at.

## Candidates

Sizes are the actual GGUF files; "fits" means VRAM weights plus a 16K-context
KV cache at four parallel slots inside 40,960 MiB.

| Model | Shape | License | Quant that fits | Thinking | Why it is on the list |
| --- | --- | --- | --- | --- | --- |
| `Qwen/Qwen3.8-27B` | 27B dense | Qwen | UD-Q4_K_XL 17.6 GB / UD-Q6_K 22.0 GB | configurable | incumbent; control arm |
| `Nanbeige/Nanbeige4.3-33B` | 33B dense, Llama arch, 512K ctx | Apache-2.0 | AD-Q5_K_M 22.6 GB / Q5_K_M 24.7 GB (**Q6_K 30.1 and Q8 35.2 do not fit**) | on by default (`enable_thinking`) | released explicitly as a distillation teacher for a future 3B; the biggest model that still fits |
| `google/gemma-4-31B-it` | 31B dense, 256K ctx | Apache-2.0 (Gemma 4 license) | Q4_K_M 18.3 GB / Q6_K 25.2 GB | configurable | best prose and instruction lineage of the four; multimodal, but we feed text |
| `meta-models/Muse-Glimmer-30B` | 30B MoE | Apache-2.0 | UD-Q6_K_XL 26.3 GB / Q8_0 29.6 GB | controllable effort | agentic tool-use focus; included because its GGUF is widely mirrored |

Caveat that applies to all three challengers: their published benchmarks are
agentic coding, tool use, and cowork tasks, measured with thinking on. None of
that is the axis this task rides on, so **the benchmark table is not the
selection evidence**. And because the card is 40 GB, a 33B challenger runs at
Q5 while the 27B incumbent runs at Q4-Q6 — a size win bought with a quant
loss, which is why the quant control arm exists.

## Excluded, with the reason

- **DeepSeek-V4.1-Flash-1017** — the available GGUF is IQ2 sharded at ~40 GB
  per shard, roughly 160 GB total. It does not fit 40 GB of VRAM, and CPU
  offload of ~120 GB across 83 GB of host RAM is not viable at all. It is also
  the family the eval judge runs on; a teacher and a judge from one model share
  blind spots.
- **flint (40B / A2.5B)** — agentic coding (SWE-bench, Terminal-Bench). Wrong
  task, and the 2.5B active budget is spent on tool syntax, not prose fidelity.
- **Underdog-Saluki-27B, Swift-1.5-Qwen3.8-27B, any `Qwen3.8-27B-GSQ-RCO`
  build** — these are **quantizations and derivatives of the incumbent**, not
  upgrades. They have millions of downloads and read like upgrades; they are
  not.
- **Ling-3.1-flash (512 experts), Hy-Memory-30B-A3B** — footprint unverified;
  revisit only if all four arms above disappoint.

## How the choice gets made

The instrument already exists: the behavioral pre-gate inside the capture
notebook (nine probe items plus five capture rows, hard stops on thinking
leaks, empty replies, and cap-hits; ceilings printed, not gated). Run it per
candidate, same rows, same serving settings (`-c 16384 --parallel 4
--cache-reuse 256`, max 250 generated tokens), one arm at a time.

**Promotion rule, fixed before the runs:** a teacher wins only on captured-row
quality — verbatim quote rate, refusal correctness on out-of-book rows, zero
thinking leaks, zero cap-hits, and a gloss that introduces no new fact.
Training loss and public benchmarks do not count.

Cost: roughly one hour of A100 per arm; five arms (incumbent, incumbent-Q8,
and three challengers) is four to six hours, no training, no repo code change.

## Guards

- Probe rows and capture prefixes must not touch the reserved or locked cases
  (`data-quality-and-retraining-2026-10-29.md`, work order 4 and 5).
- Never call the 7B "the teacher" without "original" (`AGENTS.md`, naming
  trap).
- One factor at a time: do not swap teacher **and** base model in the same
  run, or neither result can be attributed.
