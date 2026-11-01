# Multi-passage synthesis evaluation — pre-registered spec (2026-10-19)

Status: PRE-REGISTERED. Written before any synthesis output exists. Changing a
threshold after seeing sealed-set results is not allowed; a change needs a new
dated note that says what changed and why, and the old verdict stays on record.

Question: can a 1.5B-3B local model, behind a purpose-built synthesis mode,
answer broad / comparative / lifecycle questions across several passages better
than today's `ask` and `answer` modes, without losing factual truth or provenance?

Constitution that still binds (GOAL.md / AGENTS.md): local-only inference
(Ollama on 127.0.0.1:11434); stdlib-only engine code; grounded (text comes from
the book, repairs never invent text); refusal is exactly `Not in this book.`;
measured, not asserted. The only cloud call allowed is the eval judge
(`muse-spark-1.3-contributor`, key from env or `.judge-key`, never printed,
never committed). No downloads without a megabyte number approved by the owner.
Do not commit. Prototype code lives under `artifacts/probes/synthesis-2026-10-19/`
and is NOT wired into `answer.py` / `server.py`.

## 1. Arms (systems under test)

| Label | What it is |
|---|---|
| S0 | current `ask` mode, unchanged (retrieval + quote + gloss) |
| S1 | current `answer` mode, unchanged |
| S2 | naive synthesis: same 5 passages, one prompt "answer by combining the passages" (control: shows whether prompting alone helps) |
| S3 | designed synthesis (section 4): sentence-level evidence, constrained output, mechanical verify + repair, fallback to S0 |
| S3-oracle | S3 fed the gold passages instead of retrieval (isolates synthesis from retrieval) |
| S3-7b | S3 on `qwen2.5:7b` (ceiling reference: separates "model too small" from "design is flawed") |

Models: `nekohon_x3` (3B, quote-trained fine-tune), `nekohon_x3_mobile` (1.5B,
same recipe), `qwen2.5:7b` reference. Both small models were trained for the
quote-first format, so they may resist a synthesis prompt; that is part of the
finding, not a bug to hide. Base Qwen2.5 1.5B/3B are NOT installed; do not pull.

Decoding: temperature 0, fixed num_predict cap, same keep_alive/options as the
engine. Same retrieval (`answer.retrieval_context`) for S0-S3 so only the
answering step differs. Record per ask: latency, time-to-first-token, LLM calls,
tokens in/out, passages shown.

## 2. Test suite (what to ask)

About 130 questions, stratified, each with gold facts. Authored by reading the
book chunks, NOT by looking at any system output. Authoring model is not the
judge model.

| Category | n | Why it is in the suite |
|---|---|---|
| A single-fact control | 20 | synthesis must not get worse where ask already works |
| B multi-passage, one chapter | 20 | definition + purpose + example split across chunks |
| C lifecycle / across stages | 20 | needs ordering and several chapters |
| D comparative | 20 | A vs B (batch/streaming, ETL/ELT, lake/warehouse...), tempts cross-wiring |
| E enumeration | 10 | "what are the X" across passages, tests completeness and invented items |
| F trap | 15 | premise false, term only passing-mentioned, two concepts the book never relates; right answer is refuse or answer only the covered part |
| G out-of-book | 10 | exact refusal |
| H partial coverage | 15 | book covers part; right answer says what it covers and stops |

Gold per question: required atomic facts (each tied to chunk ids), the gold chunk
set, the expected behaviour (`answer` / `refuse` / `partial`), and an
`acceptable_extra` list (true statements that are fine to add). Each question is
tagged `retrieval_ok` if the gold chunks reach the shown top-5 under the live
retrieval, else `retrieval_limited`. Report everything stratified by that tag.

Split: `dev` (about 40%, prompts may be tuned on it) and `sealed` (about 60%,
never opened until the final run, run exactly once per arm). Splits are
stratified by category and recorded with a content hash. Paraphrase each
question once into `variant` text (same gold) and run both, to expose prompt
brittleness.

## 3. Success criteria (what "better" means)

Faithfulness is a gate. Completeness is the prize. A fuller answer that adds one
wrong claim does not win.

Per answer, judged at the claim level (section 5):

- claim_precision = supported claims / all claims (PARTIAL counts as 0.5)
- contradiction_rate = answers with at least one CONTRADICTED or CROSS-WIRED claim
- fact_recall = gold facts stated / gold facts (PARTIAL 0.5)
- citation_precision = claims whose cited passage really supports them / cited claims
- refusal_correct (F, G, H): exact `Not in this book.` for refuse items, no
  invented content for partial items
- latency (ms), length (words)

Mechanical checks (no judge, run first, they anchor the judge): every number and
every capitalised term in the answer appears in the shown passages; every
citation tag points at a shown passage; sentence 4-gram overlap
(`artifacts/harnesses/groundedness.py`); no repetition loop.

Decision rule (pre-registered, evaluated on SEALED, `retrieval_ok` items, small
models, S3 vs the better of S0/S1 per category):

1. Gate: S3 claim_precision >= 0.95 AND contradiction_rate <= 0.03, and S3
   claim_precision no more than 0.02 below the better existing mode.
2. Prize: S3 fact_recall beats the better existing mode by >= 0.15 absolute
   on categories B-E, paired bootstrap 95% CI excludes 0 (10,000 resamples).
3. No regression: category A recall and precision not worse than S0 by more
   than 0.02; F/G/H refusal behaviour not worse than the best existing mode.
4. Cost: p95 end-to-end latency <= 6 s warm on the owner's RTX 3060 Ti.
Verdict: SHIP (all four hold on both small models), SHIP-FOR-3B-ONLY, SHIP-
BEHIND-FLAG (prize holds, gate misses by <= 0.03), or DO NOT SHIP. Also report
the S3-oracle gap (how much of any failure is retrieval, not synthesis) and the
S3-7b gap (how much is model size). A pairwise preference score is reported but
never decides.

## 4. Synthesis design for a 1.5B-3B model (S3)

Principle: the small model never composes freely from five long passages. Code
does selection and checking; the model only rewrites short, tagged evidence.

1. Evidence selection (code, no LLM): split the 5 passages into sentences; score
   each sentence for the question (dense score from the existing embedder plus
   lexical overlap); keep the top 6-8, at most 2 from one passage unless the
   passage is the only source; keep reading order; tag `[E1]..[E8]` with the
   source chapter and passage id carried alongside, never typed by the model.
   This cuts the prompt from about 1,750 tokens to about 600.
2. Plan by question shape (code): compare -> "A / B / Both" slots; lifecycle ->
   ordered steps; list -> bullets; else short paragraph of bullets. Shape comes
   from the existing intent classifier, with no book-specific words.
3. Constrained generation (Ollama): one call, JSON schema via the `format` field,
   `points: [{text, evidence}]`, `evidence` an enum of the valid `E` ids, max 5
   points, text max about 35 words. Fallback if the model ignores schema: a
   line format `- text [E3]` parsed by code.
4. Mechanical verify (code): each point must (a) cite a valid id, (b) share
   enough content words with the cited sentence, (c) add no number or capitalised
   term absent from the evidence, (d) not repeat another point. A failing point
   is replaced by the verbatim cited sentence (extractive repair; never invented).
5. Fallback: fewer than 2 surviving points, or a refusal signal, -> return the
   current `ask` result unchanged. Refusal stays exactly `Not in this book.`.
6. Render: bullets with `[Ch. N]` tags mapped from evidence ids by code.

Also run ablations on dev only: (i) no schema, (ii) no verify, (iii) all 5
passages instead of sentences, (iv) 3 vs 6 vs 8 evidence sentences. Report which
component carries the result.

## 5. Judging pipeline

Blind and structured; the judge never sees system names.

- Randomise system labels per item; normalise tag format (`[Ch. N]`), drop the
  `Read as:` line, and report length as a covariate (also a word-capped run).
- Judge call 1 (answer only): extract atomic claims as JSON.
- Judge call 2 (claims + shown passages + full text of any cited passage): label
  each claim SUPPORTED / PARTIAL / UNSUPPORTED-TRUE-ELSEWHERE / UNSUPPORTED /
  CONTRADICTED / CROSS-WIRED (supported only by a passage about a different
  concept than the claim names), and whether the cited passage supports it.
- Judge call 3 (answer + gold facts): per gold fact YES / PARTIAL / NO.
- Temperature 0; every item judged twice; keep per-item disagreement.
- Pairwise (S3 vs best existing), both orders, secondary only.
- Resumable: append one JSON line per judged item, skip done items on restart.

Judge calibration BEFORE trusting it: build a planted-error set from known-good
answers: swap a number, cross-wire a term from another chapter, add a true fact
that is not in the shown passages, drop a key fact, forge a citation, add an
invented list item. Measure detection rate per defect type and false-alarm rate
on clean answers. Also compare with the offline `granite4.1:8b` judge on a
sample (agreement, Cohen's kappa). If detection of any defect type is < 0.85, the
hallucination numbers for that type are reported with that caveat and bounded.

Meta-judge (independent sub-agent, runs last): re-derives ground truth from the
book text only, blind to judge verdicts, on a stratified sample (all items where
mechanical checks and the judge disagree, all CONTRADICTED/CROSS-WIRED, every
S3 claim the judge marked SUPPORTED on 20 random S3 answers, plus 20 random
others), then compares. It reports false-negative hallucination rate of the
primary judge, audits gold facts for 20 questions, and issues corrected scores.
Headline numbers are shown both raw and meta-corrected.

## 6. Process rules

- Every agent writes results to files as it goes (JSONL append) and keeps a
  `STATUS.md` in its output folder so another agent can resume after a quota or
  session loss.
- One GPU-heavy agent at a time. Judge calls go to the cloud relay and are not GPU.
- Raw outputs go under `artifacts/runs/` or `artifacts/scratch/` (gitignored);
  a result is promoted into `artifacts/` only when a report names it.
- A failing or surprising result is reported as such. No threshold edits after
  the sealed run.

## 7. Amendment 1 (2026-10-19, BEFORE any synthesis output on the sealed set)

Trigger: the dataset builder's retrieval tagging (counts only, no system output)
showed category C is 20/20 `retrieval_limited` (top-5 dense retrieval cannot
reach three distant chapters), and only about 31 sealed items are `retrieval_ok`
across A/B/D/E. Section 3 as written would leave category C with no scored items
and the prize test underpowered. No answer from any arm on sealed items had been
seen when this was written; the change is made from retrieval tags alone.

Changes (everything else in sections 1-6 stands, thresholds unchanged):

1. New arm S3-wide: S3 with a wider candidate pool. Retrieve the top 12 passages
   (not 5) using the same retrieval ranking, then sentence-level selection picks
   the 6-8 evidence sentences, so the model prompt stays small. No change to
   S0/S1/S2/S3 (they keep top-5, as shipped).
2. Category C is scored on S3-oracle and S3-wide only (S0/S1/S3 on C are still
   run and reported, flagged retrieval-limited, not used for the prize test).
3. The prize test (condition 2) is evaluated on the pooled set: retrieval_ok
   items of B, D, E, plus category C under S3-oracle vs the better existing mode
   given its own oracle passages (S0/S1 are also run with oracle passages on C
   so the comparison is like for like). Report the retrieval_ok-only and the
   pooled results separately.
4. Power note: with about 31 + 12 items the bootstrap interval will be wide. An
   interval that includes 0 or that straddles the +0.15 threshold is reported as
   INCONCLUSIVE, not as a pass or a fail. Add INCONCLUSIVE to the verdict list
   in section 3 (SHIP / SHIP-FOR-3B-ONLY / SHIP-BEHIND-FLAG / DO NOT SHIP /
   INCONCLUSIVE). Effect sizes and intervals are always printed.
5. Every table reports S3 split into synthesized vs fell-back-to-S0, with the
   fallback share per model (fallback answers are S0 answers).
6. The prototype's S2 refusal normalisation (case fix) is reported both raw and
   patched; the raw number is the one used in the decision rule.
