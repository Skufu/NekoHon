# Coach handoff — teacher upgrade for "ask this book" (2026-10-15)

**Superseded in part (2026-10-15 evening):** after this document was sent,
its review came back and the kit changed — the capture was rebuilt at 515
rows (v2 rebalanced forms), the Colab notebook is at v3 (Q4 teacher,
4-slot serving, behavioral pre-gate, resume-by-id, max 250 tokens), and the
finetune notebook derives epochs from the row count. This document is kept
frozen as sent; the deltas and the answers to its questions are in
`coach-review-response-2026-10-15.md`.

**You are an external reviewer with zero context on this project.** This
document is written so that everything needed is inside it — you cannot open
the repo. Read it, then do what the next section asks.

---

## 0. What we want from you

We are about to spend an expensive GPU session (a Google Colab A100, roughly
1.5-3 hours of generation plus downloads) to capture training data from a
much smarter "teacher" model, in order to train a small local student model.
Before spending it, we want a strong outside review.

You are welcome to:

- **Ask questions — anything.** The human who sent you this will relay your
  questions back and answer with measured data where we have it.
- **Comment freely, anywhere, no politeness needed.** We would rather hear a
  flaw now than burn the session and a training cycle on it.
- **Disagree with the design choices** (model, quantization, sampling, gates,
  data mix) — say what you would do differently and why.

Specific asks, in priority order:
1. Poke holes in the **capture plan** (section 5) and the **tests/gates**
   (section 6). What is under-tested, over-tested, missing, or wasteful?
2. Attack the **open questions** in section 7 — those are the ones we know we
   are unsure about.
3. If you had this exact setup, what would you change before pressing run?

---

## 1. The product, in brief

"ask this book" is an offline book companion. One EPUB (*Fundamentals of Data
Engineering*, ~1040 index chunks) is indexed on a local machine. The user
asks a question in a small local web window; a local model answers **only
from the book's retrieved passages**. Two modes:

- **answer mode** (the default): the model writes freely, and its `[Ch. N]`
  tags become citations. Quotes the passages cannot back are stripped.
- **ask mode**: the model must quote one sentence verbatim;

The contract (frozen): each answer is either a cited answer — a verbatim
book quote tagged `[Ch. N]` plus one short plain-words gloss line — or the
exact refusal sentence `Not in this book.` Nothing is generated from model
knowledge; groundedness is the entire point.

Hard constraints:

- **Inference is local-only** (the shipped app talks to a local runner on
  127.0.0.1; no cloud at runtime). The only build-time exceptions so far: an
  evaluation judge that may be cloud, and now this teacher capture, which
  happens on Colab.
- The engine is Python stdlib only; the model runner is Ollama on
  Windows/macOS today.
- The **shipped student model must stay a stock GGUF** (loadable by standard
  runtimes) so the app can run on Windows, macOS, and later phones. Bigger
  build-time machinery never ships.

## 2. The model situation

We distill a big "teacher" into a small "student":

- **Student (ships):** `smallbook_x2d` — Qwen2.5-3B-Instruct + LoRA, q4
  (~1.9 GB), trained on ~328 rows (274 answer + 54 refusal). Runs on a
  laptop; the whole point of the project.
- **Teacher (used for the last build):** a local `qwen2.5:7b`. All training
  targets were captured by running it through the app's own prompt seam at
  temperature 0.
- **Teacher (this upgrade):** a **Qwen3.8-27B** class model, served on Colab
  with llama.cpp. Two candidates, both stock-GGUF, Apache-2.0:
  - **Saluki 27B** (`ConwayResearch/Underdog-Saluki-27B-1.0`, IQ2-mix,
    7.89 GB) — a ~2-bit quant of Qwen3.8-27B tuned to keep instruction
    following; vendor reports IFEval/IFBench slightly above the full model.
  - **Full-size Qwen3.8-27B** (unsloth UD-Q4_K_XL, ~17.6 GB).
  A third option (Bonsai ternary 27B) was dropped: it needs a custom
  llama.cpp fork, which would break our serving pipeline.

Why upgrade: the 7B teacher has measured **ceilings** (see below) — some
query shapes it simply cannot answer correctly, so no amount of distillation
from it can teach the student those shapes. A 27B-class teacher plausibly
clears them, which converts those classes into teachable data.

## 3. Measured results so far (all numbers are real, from recorded runs)

**The gate** — a sealed 21-item "fragment suite" (weird user-style queries:
bare fragments like `how do`, bare topics like `Time Series`, order flips
like `column-oriented vs row-oriented` both ways, trailing-letter typos,
greetings, 2 out-of-book controls), 10 draws per item at temperature 0. The
sealed items are never trained on; the suite is the exam.

| class (draws) | 7B teacher | x2d student (current) |
| --- | --- | --- |
| fragment (40) | 20 | 20 |
| bare topic (50) | 50 | 41 |
| order flips (40) | 40 | 20 |
| trailing typos (30) | 30 | 30 |
| **total /160** | **140** | **111** |
| out-of-book controls (20) | 10 | 20 (student refuses better than teacher) |

The student's 29-draw deficit decomposes exactly into: `how do` (10),
bare `Time Series` (9), the column/row order pair both ways (20), minus one
gain (`what about`, where the student beats the teacher 10/10 vs 0/10).
`why does` is 0/10 for **both** — a teacher ceiling, recorded, not trainable
from this teacher.

**An engine safety net** (already shipped): an uncited answer-mode reply is
retried once with the assistant turn prefilled `[Ch. ` and kept only if a
verbatim-quote citation validates. This alone took the student from 21/160 to
111/160, and did nothing for the teacher (it was already at ceiling).

**Second book** (portability test, a different EPUB): the refusal boundary
transfers (0 false refusals in-book; controls exact), and after a
chapter-label ingest fix, citations transfer too (student: 8/11 non-control
answers tagged). The teacher hallucinated a citation on one control; the
student refused correctly.

**Owner-style probe** (30 hand-typed messiness items: statements, shorthands
like `what's auto scanning?`, contractions, possessives, punctuation noise,
typos, degenerate input, false premises, cross-book contamination): 14 pass /
6 partial / 1 fail. The one fail is a `why's` contraction false refusal that
the teacher also fails (another ceiling). Whitespace-only input returns an
arbitrary grounded quote — a known engine gap, not a training item.

**Known ceilings (teacher cannot do these; not trainable from it):**
`why does`; `why's kafka so popular?` (and the uncontracted form too).
**Known student gaps (teacher-passable; trainable):** the four gate deficit
items above, plus uncited answers for `Location`, `DE Lifecycle`,
`ddr4 vs ddr5`, `lambda vs kappa`.

## 4. The plan under review

**One Colab session, all value extracted:**

1. **Prep (done, local, free):** every prompt for this session was frozen
   locally by running the app's real prompt-building code with a fake
   generator — so the Colab side sends the *exact* prompts the app uses, not
   improvised ones.
2. **Session:** install pinned llama.cpp (nightly `b11617`, CUDA build, asset
   URLs verified), serve the teacher (`llama-server --jinja -ngl 99 -fa on
   -c 32768`), force **thinking off** (`chat_template_kwargs`), temperature 0,
   max 768 output tokens. Then: a smoke gate → the **full 555-row capture** →
   download. Weights cache on Google Drive between sessions; optional MTP
   speculative-decoding flags for the big model.
3. **After (local, free):** parse → verbatim-quote verification → refusal
   checks → seal check (no training item near-matches the sealed 21) →
   contamination probe → choose the final answer/refusal mix → build the
   train jsonl.
4. **Training session (existing proven notebook):** LoRA on Qwen2.5-3B,
   ~6 epochs, export q4 + q8, download (~1-1.5 h).
5. **Gate re-run:** the sealed suite (10 draws), the battery, loop counting,
   controls, a quant spot-check, a revert rehearsal. Adopt only if it beats
   what we have; record everything either way.

**Why one big capture instead of a small probe first:** on Colab the
expensive parts are session spin-up and the 8-18 GB download; once loaded,
each generated row costs ~10-20 s. A 555-row pass is ~1.5-3 h of generation.
A 9-item probe would waste the session.

## 5. The capture file (what gets sent to the teacher)

**555 rows**, two parts:

- **328 "re-capture" rows** — every existing training row's (system, user)
  prompt pair is re-used verbatim. Same prompts the old teacher answered, now
  offered to the much smarter teacher, so the student's *entire base* can be
  retrained on uniformly higher-quality targets rather than patchwork.
- **227 "new" rows** — forms for the measured deficits, generated by a
  guarded pipeline (349 candidates → 227 accepted). Each row carries
  `expect: cited | refusal` and, for cited rows, a candidate gold chunk id.
  Composition: ~15-19 forms each for `Time Series`, `column-oriented vs
  row-oriented` (both directions), `Location`, `DE Lifecycle`,
  `ddr4 vs ddr5`, `lambda vs kappa`, `auto scanning`; 20 short
  fragment-shape queries; 65 refusal-side rows (topics provably absent from
  the book — contamination items from the second book + everyday off-book
  topics).
- Totals by expectation: **436 cited / 119 refusal (21.4% refusal)**.

**Guards every new form passed** (rejection counts from the run):
near-match to the sealed 21 (reject at difflib ≥ 0.8 or token-Jaccard ≥ 0.6)
— 29 rejected; near-match to any existing train/bench question — 9;
near-match to the owner's previously-probed questions — 16; near-match to
the visible trial queries — 6; near-match to the bench "greet" template — 9;
forms whose typo-repair would silently rewrite the ask — 12; topic not in
book — 1; retrieval preflight missing its pin chunk — 1; duplicate among
candidates — 14; per-card cap — 25.

Notable catches: the bare topic `Time Series` **cannot be trained as asked**
— it is literally the sealed exam item, and any near-form trips the seal
guard; 17 seal-clear variants passed instead. `DDR4` occurs **zero** times in
the book (only DDR5, in a RAM passage). `ch06-067` never surfaced in
retrieval for any column/row form.

**What a prompt looks like** (one row, truncated): the system prompt is:

> "You answer only from the passages below. If the passages do not contain
> the answer, reply with exactly this sentence and nothing else: `Not in this
> book.` …" *(597 chars; full text includes the quote-or-refuse rules and
> the citation format)*

The user message is `Question: <asked form>` + a passages block of 5
retrieved chunks, each labeled `[Ch. N] chunk_id=chNN-NNN` + text. Expected
targets: a verbatim quote + `[Ch. N]` + one gloss line, or the exact refusal
sentence.

## 6. Tests and gates (what exists)

- **Sealed fragment suite** — the main gate, described above; 10 draws;
  never trained on.
- **Battery** — 14 scripted asks (golden questions, typos, probes, an
  out-of-book control); pass/fail per pin.
- **Loop counting** — any generation ending at the token cap counts as a
  loop; loops are tracked per suite class.
- **Contamination probe** — checks train rows against bench questions
  (near-twins are logged; some bench passes are "assisted" by design).
- **Seal check** — aborts a build if any form near-matches the sealed items.
- **Owner-style probe** — 30 messiness items, exploratory (not a gate).
- **Second-book probe** — portability evidence.
- **Judge** — an LLM judge exists for softer qualities, but it is
  deliberately **not** in the adoption gate (single draws are noisy).

## 7. Open questions / weak spots (attack these)

1. **The pre-run behavioral gate is thin.** Today the session's smoke gate
   is one trivial prompt (serving works, thinking is off). We own a 9-item
   behavioral probe (the ceiling items + format controls) that could gate
   the big run instead — ~10 minutes versus risking 3 h of generation from a
   model that holds the contract poorly. Worth it?
2. **Re-capture assumption.** We assume "same prompts, smarter teacher =
   better targets." But the 27B may answer *differently in style* (longer
   answers, different quote choice). Verification enforces the format
   (verbatim quote, exact refusal) but **not** style. What would you check
   before training on re-captured rows?
3. **The refusal ratio.** Capture superset is 21.4% refusal. The current
   student trained at 16.5%; an earlier experiment at ~32% caused generation
   loops. Where would you set the final mix, and what would you watch?
4. **`Time Series`.** The exact bare form is the exam item → untrainable.
   Is "train 17 nearby forms, still fail the exam item" acceptable, or would
   you restructure the gate (re-seal that item) to free the form for
   training?
5. **`ddr4 vs ddr5`.** The user asked this in real life; DDR4 is absent from
   the book. What should a faithful book companion do with a comparison
   question half-covered by the book — refuse, or answer the covered half
   with citations?
6. **Ceilings.** The old teacher can't do `why does` / `why's kafka…`. The
   new teacher probably can — but we haven't verified. Should proving that
   be part of the pre-run gate (question 1) and, if proven, should those
   ceiling classes be added to *this* capture (they weren't), or to a second
   pass?
7. **Single-session risk.** Results now save incrementally and resume; but
   the session could still die (Colab limits). No fallback teacher is
   pre-downloaded. Acceptable for a first run?
8. **Overfitting to our own tests.** We keep one sealed suite that is never
   trained, and train on *visible* counterparts by design. Everything else
   (owner probe, second book) is exploratory. Do you see a place where we
   are measuring our own homework?

## 8. Reference (for the human, not required reading)

Files involved: capture file `data/finetune/teacher-capture-2026-10-15.jsonl`;
generators `artifacts/probes/gen-new-forms-2026-10-15.py` and
`artifacts/probes/build-teacher-capture-2026-10-15.py`; session notebook
`artifacts/reports/teacher-capture-colab-2026-10-15.ipynb`; the exam suite
and all evidence under `artifacts/`. The human can share any of these on
request (the capture file contains book passages).
