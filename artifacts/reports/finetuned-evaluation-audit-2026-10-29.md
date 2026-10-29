# Finetuned evaluation audit — 2026-10-29

Status: audit **COMPLETE**. Semantic grading and the prompt-comparison pilot are **BLOCKED** — not pending, not running. Calibration v3 is 21/22 fixtures; one source-grounding inference control is unstable. There are no candidate content grades, no content-correctness percentage, and no "after" improvement. All 26 old raw model captures and legacy baseline findings remain real at their recorded hashes. No production code, model, config, dataset, frozen grader file, or commit was touched; the tree was already dirty.

## Measured snapshot

All four are pipeline numbers on `nekohon_q35_2b_x3_2e` (digest
`cba00d4abf1f…`), not model-only numbers.

- **Hard multi-turn: 12/12**, reproduced twice. The 12 items are 8 distinct
  histories and 8 distinct gold sets, and the bench was fixed from 8/12 to 12/12
  against its own failures. It is a regression gate, not a generalization
  estimate.
- **Sealed: 28/30**, one run only, legacy rule. Scoring is a `key_fact` regex
  over the whole answer plus exact refusal; there is no citation or support
  gate. The two failures are key-fact misses.
- **Hard bench: 53/60 legacy; 45/58 structural (credible)**, excluding
  `varied_comp_04` and `varied_comp_05`, whose glosses are code templates.
  Structural is not a content certification.
- **Adrian: 31/35** citation/format score in `--direct` mode; 90/94 answer turns
  and 3/3 refusals. Of 88 authored answer turns, 76 have no positive content
  requirement beyond a chapter citation and two lines.

No headline says an answer is correct. The legacy rules check keywords,
citations, refusals, and shape; the structural rule checks quotation and
grounding vocabulary. None checks whether the gloss answers the question.

## Question coverage (measured strings)

- Sealed: 30 rows, 29 distinct normalized questions, 22 definition items, 13
  `what is/are` forms.
- Hard multi-turn: 12 distinct final questions, 8 histories, 8 gold sets, four
  categories with three items each.
- Hard bench: 60 distinct questions, six categories with ten each; 45 answer and
  15 refusal items. Equal category counts are not independent evidence.
- Adrian: 97 turns, 94 answer and 3 refusal turns, 88 authored answer turns, 62
  distinct authored questions. Repeated follow-ups include `why` x4,
  `explain more simply` x3, `what problem does this solve` x3.
- New dev set: 26 cases, 18 `variant_of` roots, 8 perturbation categories, 10
  reserved cases not run.

These are exact-string counts, not meaning-preserving pair coverage: a
paraphrase counts as a separate question, and a repeated concept stays repeated.

## Not an improvement, not a proven regression

- Old sealed artifact: **27/30** on dataset sha256 `7f1dfd6a…`; measured:
  **28/30** on `24fcc1c9…`. The bytes differ, so the +1 is not an improvement.
- Hard multi-turn was 12/12 historically and 12/12 now, but the evidence hash
  changed (`318d3c40…` to `a45d80a0…`); equality is not a win.
- Hard bench was 59/60; the same harness now reads 53/60 legacy. Six verdicts
  flipped, all losses. The historical artifact stores no model digest and the
  engine changed after measurement, so this is not attributed to the model and
  not called a regression.
- Adrian was 32/35 on the 2026-10-17 artifact; measured 31/35. `adrian-16` is a
  unit false negative (`ns` vs `nanosecond`); `adrian-07`, `adrian-19`, and
  `adrian-31` are substantive under the gate. No historical digest is recorded.

The measured runs used `answer.py` `6fb7e844…` and `observe.py` `503a31c1…`. After the last suite, `observe.py` changed at 17:23:50 to `862d9a3e…` and `answer.py` at 17:26:46 to `40496d17…`. Those edits were outside this audit; it did not make, attribute, or revert them, and it preserves the production changes. Earlier source findings (no prompt/full-completion capture, 600-char preview, absent `trace_inspect.py`) are **snapshot claims** at those initial hashes and times, not current-tree defects. `trace_inspect.py` appeared after the runs; whether the changed `observe.py` still has the 600-char preview or an inspector now exists was not verified. This session's measurements and sources belong to the earlier frozen fingerprint; a current externally changed engine baseline is pending.

## What the gates actually measure

**Hard multi-turn.** The only suite that checks whether a cited passage carries
the item's terms; it does not check quote fidelity. It was authored, scored
8/12, had an ambiguous item replaced, then three engine fixes were written
against its failures to reach 12/12. Its 12 rows are 8 distinct setups, with two
histories reused by three items each.

**Sealed.** The current 28/30 is 25 answer + 3 refusal passes. An echo of the
question with no citation passes **18/30**, exactly the items whose authored
`key_fact` matches their own question. A generic sentence scores 0/30; refusing
everything scores 3/30. The allowlist records `sealed-def-02` as a known
training overlap in `train-x3`; the corpus is absent, so this is a **record, not
a re-read corpus check**. If accurate, the remainder is 27/29. The set was used
repeatedly to choose between candidates, so "held-out" is not supportable.

**Hard bench.** Five built-in negative controls were rejected 5/5. The
structural rule checks a citation id, a verbatim quote **when one is present**,
a non-echo gloss, question-type match, and one uncommon shared term. It excludes
the two template-gloss items. It does not require a quote and does not check
answer correctness. Content hint is advisory: 18 of 31 credible answer passes
match the authored key fact, 9 explain items have none, and 4 miss it but count.

**Adrian.** The gate requires two lines, a chapter citation, and sometimes
`must_contain`. Only 12/88 authored answer turns have a positive content check;
63/88 have chapter as the only requirement class. A generic two-line answer plus
the expected-chapter citation passes **76/88 authored answer turns**, not 76
scenarios. Six pill turns grade engine-generated questions, not a frozen list.
The score is a citation/format measure.

## Measured control failures

- Hard bench: emptying every citation quote leaves **31/31** credible answer passes passing; a bare `[Ch. N]` first line also leaves 31/31. Replacing the gloss with another verbatim sentence from the same cited passage leaves **30/31** structurally passing; those replacements were not semantically reviewed, so this is response-insensitivity evidence, **not 30 confirmed wrong answers**.
- The other fake controls are reported above: sealed echo **18/30**, adrian generic-plus-citation **76/88 authored answer turns**, hard-mt echo-plus-gold **3/12**. None is semantic.

## Model-only arm on frozen dev variations (T1)

The dev file is 26 cases, sha256 `81c47351…`: 18 `variant_of` roots across 8
perturbation categories, not 18 proven-independent topics; no interval should
be computed over 18. The reserved 10 were **not run**. The suite scorer was not
used.

Model bytes only, with the exact retrieved passages and `prompt.SYSTEM`:

- **2/2** fabricated-premise traps returned exactly `Not in this book.`; zero
  traps answered.
- **0/24** answerable cases refused; **24/24** carried a `[Ch. N]` tag.
- **Quote integrity (model-only, measured):** 24 long spans (>=20 chars) were
  audited only in their tagged chapter: **22 byte-literal**, 1 case/whitespace-
  only (`dev-b3`), 1 U+2060-removal-only (`dev-d2`), 0 failed, 0 unknown. One
  short 14-char inline quote was excluded. This is **not 24 strict-verbatim**;
  it is an integrity meter, not a content-truth score. The two trap replies
  contain no quote.
- **0/26** replies stopped at the output-token cap.
- 25/26 model-only prompts were byte-identical to a prompt the engine sent; the
  26th is the guard-blocked fabricated person, called explicitly on the same
  evidence. 25/25 identical prompts produced byte-identical replies.

Retrieval diagnostics, not answer verdicts: a gold chunk appears in top-5 for
**20/24** answerable cases; exact engine citation is gold for 13/24. The four
gold-top5 misses (`dev-f1`, `dev-f2`, `dev-g1`, `dev-g2`) are **not
availability failures**: an independent check found valid alternative evidence
in the shown chapters (Ch. 3 definitions for `dev-f1`/`dev-f2`; Ch. 6 catalog
descriptions for `dev-g1`/`dev-g2`). They are label misses, not missing
evidence, and not wrong-answer proof.

Pipeline effect, measured separately: model reply and reader answer are
equivalent after normalization in 10/24 ask-mode and 11/24 answer-mode cases;
the rest contain code-built text. This is why pipeline scores cannot be read as
model scores.

T1 is the captured exact model-only prompts and raw outputs; it remains valid
across engine changes if replayed identically. T2, the current pipeline, needs
a fresh stable source before comparison.

## Concrete findings (source-checked agent review, not calibrated truth)

Primary verified finding: `dev-f3-insert-only-vs-crud` raw main omits insert-only
although both facts (`ch05-020`/`ch05-021`) are shown — a **model completeness
failure under the main prompt**. Comparison aux calls produce a correct
two-sided draft unused in the final body — a possible candidate-selection issue,
cause unknown and not proven.

The f1/f2 pair changes quote choice, but also evidence sets and order; do **not**
call it isolated wording-order sensitivity. g1/h2 show possible gloss overreach;
absence of a word is not falsity, so they are not proven false. All four
apparent gold misses have valid alternative passages. Evidence:
`concrete-weaknesses.md` (`d9b52afa…`).

## Grader validity

The v1 variation scorer is not a content measure. On 15 fixtures it falsely
accepted **10 of 13 negatives** while correctly accepting both positives. Its 12
red tests are 12 fixtures, not 12 bad answers; 2 failing assertions concern
certification on correct positives, not wrong content.

V2 rejects fabricated quotes, citations outside the shown set, echoes,
template glosses, and generic glosses; those checks stand. But its check 9 is
lexical: a correct all-synonym paraphrase sharing no content word is
**false-rejected**. V2 never reports a content pass; uncertain content goes to
the blind judge. Do not report its rejection rate as a content-error rate or let
it filter submissions before the judge.

References and controls are agent-authored and source-checked, not
human-validated; calibration labels must not be called "human". No content
truth claim exists for v1 or v2.

## Semantic calibration — v3 BLOCKED, pilot not executed

V1 remains BLOCKED on the `t07` prompt/metric mismatch; V2 remains BLOCKED on
positive `t06` (1 accept, 2 rejects). Neither metric is reclassified; all old
failed runs and frozen files stay intact.

V3 ran the repaired 22-task reference with the exact v2 prompt/rubric
(`73a2d864…`/`5cd19b75…`): **21/22 fixtures majority-correct**, 4/4 true
paraphrases, 16/16 old hard negatives, and the new watermark
unsupported-added-claim negative correct. It made 66 valid calls with zero
transport, model, or axis errors; temperature 0 configured, not wire-verified.

It is still BLOCKED on preserved old-t06 negative `r3-9011ed66`: 2 accept,
1 reject. The shown paragraph supports "integer offset" and accuracy/sparsity
effects, not "represent zero exactly" or "why it beats fixed-point." This is one
source-grounding inference-boundary instability on a required control, **not** a
claim that the judge is useless or a 21/22 general-accuracy estimate. No
criterion loosening, no relabel, no retry, no candidate grade.

Source-first lesson: book truth is not the same as support by the passages shown
to the judge, and calibration labels need the same source audit as model
answers.

## Prompt pilot — prepared, NOT executed

A frozen prompt-only experiment is ready, not run: 26 dev cases x 2 arms x 2
draws = 104 calls; AB/BA order 26/26. The candidate differs only by one generic
comparison instruction appended to SYSTEM; book evidence, user message, prefill,
options, and weights are identical (`freeze.json`). Offline checks pass 22/22
with 0 network attempts. Production prompt and model weights are unchanged;
reserved 10 are untouched.

The collector must not execute until scoring is valid. No automatic retry and no
known-case prompt loop.

## Training and provenance limits

`data/finetune/` is absent, so 844 rows, 790 distinct questions, 137 refusals,
and hash `fd06f981…` remain documentation claims. Present: GGUF `1621bcb3…`,
Modelfile `60f98a85…`, script `3884f0ef…`, x3 builder `cdb005c8…`, 2-epoch table
`88eeffe3…`; no run log ties the table to the corpus.

The split groups exact normalized questions, not paraphrases. A pure 10-row
synthetic control shows a paraphrase can cross while exact duplicates stay
together; that proves the rule can leak variants, not that the adopted corpus
leaked. Builder checks are embedded-example only: ten `preface01` tags against
`preface`, 53/65 history quotes non-verbatim, and 16 second-turn forms. These are
training-side candidates, not proven runtime causes.

Unit baseline: 630 methods, **524 passed, 98 failed-or-errored, 8 skipped**; raw
events 21 failures and 80 errors on 98 methods because one method emitted four
subtest errors. This is current tree-versus-test mismatch, not historical
regression.

## Method limitations and disclosures

- The v1 variation design was blind to generated answers, **not to retrieval**.
  An early self-test accidentally invoked retrieval/search for four dev cases;
  no generated answers were produced. The self-test was then made offline and
  its temporary outputs removed. Reserved cases were never executed.
- V1 manifests are preserved as immutable inputs; no frozen version or grader file was modified.

## Before/after plan

1. **Freeze T1.** Keep captured model-only prompts and raw outputs for the 26
   dev cases; replay identical system/user/prefill/options/model digest. This is
   a valid model-only baseline across engine changes.
2. **Stabilize T2 for product claims only.** Before a current-pipeline
   comparison, record hashes for `answer.py`, `observe.py`, `retrieve.py`,
   `prompt.py`, `server.py`, and indexes; keep the tree unchanged. The source
   changed outside this audit, so T2 is not a precondition for T1.
3. **Calibrate v2, then score dev.** Freeze the two-axis rubric; fail bad
   answers, pass good answers, calibrate blindly. Run model-only and full
   pipeline separately, report paired outcomes and code-rescued items, and keep
   reserved 10 untouched.
4. **Keep claims separate.** A model-only before/after may proceed from frozen
   prompts despite T2 instability; a product/pipeline claim requires stable T2,
   valid calibration, and reserved confirmation.

## Evidence

- Runtime snapshot/hashes/logs: `artifacts/runs/finetuned-audit-2026-10-29/runtime-baseline.md`; `baseline/{hard-mt,hard-bench,adrian,sealed,variations-dev}/`.
- Scoring: `scoring-audit.md`, `scoring-controls.log`, `scoring-inventory.log`, `scoring-hardbench-control.log`, `hardbench-unrelated-gloss.json`.
- Grader correction: `variation-grader-v2-audit-2026-10-29.md`; split control: `training/split-control.log`.
- Quote audit: `semantic-replay/quote-audit.log` and `semantic-replay/PROVENANCE.md`.
- Calibration/pilot: `judge-calibration-v2/results/{calibration-v2.md,failure-t06.json}`; `judge-calibration-v3/results/{calibration-v3.md,failure-r3-9011ed66.json}`; `judge-reference-v3/{README.md,ledger.json,freeze.json}`; `prompt-comparison-experiment/{ACCEPTANCE.md,freeze.json,offline-checks.log}`.

Next check: source-based human adjudication of the inference policy and ambiguous
cases, then validation against those references before the fresh paired
experiment. Do not swap provider (Go Flash only is authorized) or retry until
green. T1 fixed-prompt baseline is valid; stable T2 is required only for the
product arm. Reserved 10 remain untouched.
