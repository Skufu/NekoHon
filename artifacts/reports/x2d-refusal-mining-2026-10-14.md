# x2d refusal mining — 2026-10-14

Deliverable shipped. `data/finetune/x2d-refusal-candidates.json` holds **27 NEW
out-of-book refusal questions**, teacher-verified through the shipped seam, so
x2d can carry 54 unique refusals (the existing 27 + these 27) instead of the
old builder's 27×2. 34 unique questions passed every gate; 27 shipped, 7 held
as named spares (the plan pre-registers exactly 54, "same count and share as
x2/x2c").

## What ran

- Miner: `artifacts/probes/mine-x2d-refusals-2026-10-14.py`. Imports the
  builder (`build-finetune-data-2026-10-13.py`) via importlib for
  `REFUSAL_CANDIDATES`, `capture()`, `TEACHER_MODEL`; index via
  `retrieve.load_index(INDEX)`.
- Acceptance: completion exactly `Not in this book.` (period included) — the
  same gate as `builder.evaluate`. Teacher `qwen2.5:7b`, temperature 0, through
  `capture` (canonical_query → retrieval_context → shipped SYSTEM prompt).
- Candidates: 45 proposed (32 obvious exotica + 13 book-adjacent near-misses) +
  a 15-name reserve batch, not probed (batch 1 alone hit target).
- Pre-teacher exclusions: normalized dup of the 28 existing candidates, the
  France/iops canaries, every asked form in train-x1/x2/x2c (164), and the x2d
  answer forms (`x2d-forms-2026-10-14.json`).
- Near-match guard: `tokens`/`normalized`/`similarity` + the ITEMS list copied
  from `probe-fragment-2026-10-14.py`; reject at difflib ratio ≥ 0.8 or
  word-set Jaccard ≥ 0.6. Candidate raw + canonical forms vs sealed items
  (raw + canonical), bench forms, the existing 28-candidate list, and the
  kept-so-far new set. Visible ten: report-only (the probe's `what is`
  metric-artifact note applies).
- Budget: 44 teacher calls total (2 smoke + 42 probing; cap 80). Wall time
  ≈ 131 s across three commands [measured: 14.1 s smoke, 116.9 s probing,
  0.3 s selection re-run with 0 teacher calls].

## Counts [measured]

| stage | n |
|---|---|
| proposed (batch 1) | 45 |
| excluded before teacher | 1 — `What is a feature store?` (train-form dup) |
| teacher-probed | 44 |
| exact refusals | 35 |
| guard rejections | 1 — `What is a data fabric?` (below) |
| kept after guard | 34 |
| **shipped** | **27** |
| spares | 7 |

Rejected pile = 10: 9 the teacher answered (named below) + 1 guard rejection.

Post-hoc re-check of the shipped 27 [measured]: 0 normalized collisions with
the 164 train forms, the 42 bench forms, the 28 existing candidates, or the
canaries; union with the 27 existing train refusals = **54 unique**.
`asked == question` for all 27 (canonical_query is a no-op on these forms), so
the new refusals keep the x2/x2c refusal surface style.

## Kept — the 27 shipped

| # | question |
|---|---|
| 1 | Who discovered penicillin? |
| 2 | How do you tie a bowline knot? |
| 3 | How many bones are in the human body? |
| 4 | What is the currency of Switzerland? |
| 5 | When did the Titanic sink? |
| 6 | How do you grow tomatoes in a greenhouse? |
| 7 | Who founded Microsoft? |
| 8 | How do you convert Celsius to Fahrenheit? |
| 9 | What is the longest river in Africa? |
| 10 | How do you fix a leaking faucet? |
| 11 | What causes a rainbow? |
| 12 | Who was the first person to walk on the moon? |
| 13 | What is the fastest land animal? |
| 14 | Who won the Nobel Prize in Literature in 2023? |
| 15 | What is an ionic bond? |
| 16 | How does a microwave oven heat food? |
| 17 | What is the largest species of shark? |
| 18 | How do you play the guitar? |
| 19 | When was the United Nations founded? |
| 20 | What is the average rainfall in the Amazon basin? |
| 21 | How many countries are in the European Union? |
| 22 | Who won the Tour de France in 2023? |
| 23 | How does a solar panel generate electricity? |
| 24 | What is the diameter of Jupiter? |
| 25 | What is a snowflake schema? |
| 26 | What is a bloom filter? |
| 27 | What is the CAP theorem? |

Mix: 24 exotica + 3 near-miss survivors (all that passed).

## Teacher-answered — rejected pile (named)

In-book evidence exists; do not reuse as refusals:

| question | answered from |
|---|---|
| How far is the moon from Earth? | wrong-chunk Ch. 7 "size of the data … bytes of a payload" — not a refusal, so rejected by the mechanical rule |
| What is a vector database? | Ch. 6 "What Is a Vector Database?" |
| How do you use dbt to build a data warehouse? | Ch. 9 "Looker and Data Build Tool (dbt)" |
| What is RabbitMQ used for? | Ch. 5 message queues |
| What is a data contract? | Ch. 5 "a written agreement between the owner of a source system…" |
| What is a semantic layer? | Ch. 9 "a tool for maintaining and computing business logic" |
| What is zero-copy cloning? | Ch. 6 "a compelling feature…" |
| What is a graph database? | Ch. 5 "designed for precisely this type of query" |
| What is an OLAP cube? | Ch. 5 OLAP systems |

These nine are measured evidence that the book's passing mentions cover this
vocabulary — useful for future near-miss selection.

## Guard rejection

`What is a data fabric?` — bench-near-match at exactly the threshold:
Jaccard 0.600 vs bench `what is data ingestion` (ratio 0.722 vs `What is data
mesh?`). Same short-form template artifact class the sealed-suite probe
documented for 4–5-token "what is X" forms. Rejected per the pre-declared rule.

## Near-match check on the shipped 27 [measured]

Thresholds r ≥ 0.8, j ≥ 0.6; worst pair per reference set:

| set | worst ratio | worst jaccard | verdict |
|---|---|---|---|
| sealed items | 0.667 — CAP theorem vs `What is Time Series?` | 0.429 — CAP vs `what is the offside rule` | pass |
| bench forms | 0.682 — CAP vs `what is the data mesh` | 0.500 — Switzerland vs `What is the capital of France?` | pass |
| existing candidates | 0.714 — bloom filter vs `What is a black hole?` | 0.500 — Switzerland vs `What is the capital of Australia?` | pass |
| visible ten (report-only) | 0.500 — ionic bond vs `what is` | 0.400 | probe artifact class |

No shipped candidate reaches a rejection threshold.

## Spares (kept, not shipped)

| question | margin = max(r/0.8, j/0.6) |
|---|---|
| What is the largest desert in the world? | 0.969 |
| What is the pH of pure water? | 0.926 |
| How do you make a paper airplane? | 0.917 |
| What is the deepest point in the ocean? | 0.886 |
| How do you knit a scarf? | 0.882 |
| Who invented the printing press? | 0.877 |
| What is the atomic number of carbon? | 0.873 |

Held back because the plan pre-registers 54 ("~27 more"), and these have the
least near-match headroom of the exotica. All 34 kept candidates with full
detail are in the audit; shipping all of them (61 unique) is a one-line change
plus a plan amendment.

## Artifacts

- `data/finetune/x2d-refusal-candidates.json` — 27 rows, the deliverable.
- `artifacts/probes/mine-x2d-refusals-2026-10-14.py` — miner (idempotent;
  replay makes 0 teacher calls).
- `data/finetune/x2d-refusal-mining-2026-10-14.audit.json` — all 44 probes,
  guard rejections, spares, per-candidate near-match worsts.
- `data/finetune/x2d-refusal-mining-2026-10-14.progress.jsonl` — teacher-call
  cache.
- `data/` is gitignored; nothing committed.
