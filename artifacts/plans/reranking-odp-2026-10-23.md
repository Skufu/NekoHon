# Reranking bake-off — pre-registered brief (2026-10-23)

**Objective:** Decide, with evidence a skeptic can rerun, whether a reranker
makes NekoHon's answers better enough to pay for it. The deliverable is a
decision, not a feature.

Format: Outcome-Driven Planning (`GOAL.md` → outcome, constraints, gate).
Strategy is deliberately not prescribed below.

---

## 1. What we have

**Baseline pipeline.** Dense cosine over every chunk with pre-normalized unit
vectors → `PASSAGE_LIMIT = 5` passages → conditional RRF fusion when the
question carries a rare book word (one lexical candidate, dense band 0.20 veto)
→ caption seeding → `_prioritize_phrase_matches`. No cross-encoder, no LLM
scoring of `(query, passage)` pairs.

**Recorded gates** (authoritative files: `BUILD_PLAN.md`, `AGENTS.md`):

| Gate | Result | Headroom for a reranker |
| --- | --- | --- |
| 60-item Hard Benchmark | 60/60 | **none — saturated** |
| 24-item golden highlights | 24/24 | none — saturated |
| 22-item HTTP battery | 22/22 | none — saturated |
| `adrian-eval.py` | 32/35 across 97 turns | 3 items |
| `crossbook-evil-eval.py` | 23/30 across 66 turns | 7 items |
| Unit suite | 385 tests, 22 suites | regression net only |

**The ceiling problem.** Three of the five gates are at 100%. They cannot show
an improvement, only a regression. Any accept/reject decision has to come from
the two unsaturated sets, plus a retrieval-level metric that is not capped.

**Labels that already exist.** `artifacts/harnesses/hard-bench.py` items carry
`gold_chunks` (ask) and `chunk_id` (explain). The adrian and crossbook datasets
name their expected chunks. Retrieval recall is therefore measurable without
writing a new question set — but only if those labels are verified to be
complete, which is itself part of the work.

**Known unknowns.** Nobody has measured: (a) the rank of the gold chunk in the
full candidate list, (b) how much a reranker moves it, (c) what that costs in
latency, RAM, and install size on this box.

---

## 2. What we want

**Target capability.** A defensible answer to one question: *does reranking
change what a reader sees, and is the change worth its cost?*

**Definition of done.** A dated report under `artifacts/reports/` containing:

1. Gold-chunk rank distribution at k=5, 10, 20, 50 on the unsaturated sets.
2. A reranked vs. baseline comparison at the answer level, on the same
   questions, with run-to-run noise stated.
3. A cost line: install size, resident memory, p50/p95 added latency, and the
   one-line revert.
4. An explicit accept or reject, and which pre-registered criterion fired.

"Reject" is a successful outcome. So is "no headroom, stop at gate A."

---

## 3. Non-negotiables

These are the constitution, not local policy. Everything else is fair game,
including new dependencies — under the rule that a dependency must show a
measured win with its cost recorded next to it.

- **Local only.** Inference on `127.0.0.1`. No cloud call on the serve path.
- **Grounded.** Every quoted word comes from a passage.
- **Refusal stays exactly** `Not in this book.`
- **Measured, not asserted.** Every number ships with its command and its
  evidence path. Unmeasured stays labeled unmeasured.
- **No silent regressions.** Unit suite, 3-book battery, and pins green at the
  end, or the change does not land.
- **One-line revert** for anything wired in.
- **Cost is disclosed with the win**, not after it.

Note on scope: constraints in this brief are themselves falsifiable. If a gate
turns out to be measuring the wrong thing, say so and replace it — with a
measurement, not an assertion.

---

## 4. What we need figured out

- How to score `(query, chunk)` pairs locally at all: an embedded
  cross-encoder, a rerank endpoint on the local runner, or the answer model
  itself scoring candidates. Pick based on measured cost, not familiarity.
- How to run the comparison without the engine change leaking into the
  baseline (an offline rescoring harness over archived candidates is one
  option; so is an env flag — the agent chooses).
- How to get a noise floor: repeated runs, temperature control, or paired
  comparison on identical candidates.
- How to keep the refusal behavior intact. A reranker that promotes a
  plausible-but-wrong chunk is worse than no reranker, and the France case is
  the canary.

---

## 5. Pre-registered kill criteria

Proposed thresholds, to be confirmed before the first run and not edited after
it. Numbers are proposals, not measurements.

| Gate | Pass condition | Kill condition |
| --- | --- | --- |
| A. Oracle recall | Gold chunk in top 20 for ≥ 80% of currently failing items | Gold chunk already in top 5 for ≥ 95% of all items → no headroom, stop |
| B. Offline rescoring | Reranked top 5 recovers ≥ 3 more gold chunks than baseline | Gain ≤ run-to-run noise, or any loss on items that currently pass |
| C. Answer-level | Net pass gain ≥ 3 items across the unsaturated sets | Net gain ≤ 0, or a refusal regression |
| D. Cost | p50 added latency ≤ 300 ms | p50 added latency > 800 ms, or footprint push that breaks the weak-machine goal |

Gate A costs no dependency and settles half the question. Run it first.

---

## 6. Reporting

One dated report, `artifacts/reports/reranking-2026-10-XX.md`, following the
repo's evidence rules: command, path, numbers, and the failures kept in the
record. If the answer is "no," the report is still the deliverable.
