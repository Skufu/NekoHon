# Query canonicalization — Stage 0 plan (2026-10-13)

Status: plan + baseline fixture only. No engine change. Stage 1 (the R1 rule
in code) waits on the fixture numbers below and the user's word.

Scope note: `query-normalization.md` rejected *blanket punctuation
normalization* (strip trailing "?"; measured net 0 on pins, 2/23 flips in
opposite directions). This plan does not reopen that. R1 is a structural
*form* canonicalization, measured after that verdict, with a different
evidence base (behavior collapse, not pin shuffling). The two documents
agree on the principle: structural rules with measured wins only, never
per-question rewriting.

## The seam, verified 2026-10-13

- `retrieve.format_input` runs `preprocess.normalize()` on both sides: the
  dense view is Unicode/whitespace-normalized, never form-normalized. That
  is the gap this plan fills, stated precisely.
- Three embed sites consume the question, all fed from
  `retrieval_context`: `search` (via `format_input`), `fuse` ->
  `dense_rank` -> `rank_chunks`, `caption_seed`.
- Two consumers read the raw question outside the seam: `anchor_words`
  (answer.py ask), `simple_words` (answer.py respond).
- `explain` is `ask` with the highlight as the question
  (`answer.explain` -> `answer.ask`); highlighted book sentences are
  structurally bare under a naive trigger. The gate is mandatory.

## Evidence base (restated — no double count)

- `probe-prefix-rule.*`: MAD + multicloud, V0 raw / V1 prompt-only prefix /
  V2 prefix before retrieval and prompt. MAD answer 2 draws per variant
  (stable per variant); ask 1 draw. MAD/V1 ask refused (KO) — the prefix
  must reach retrieval. V2 clean in both modes.
- `probe-prefix-bare-terms.*`: watermark, CRUD, data ingestion, data mesh;
  raw vs prefixed; ask pins held, answer same or tighter; 1 draw.
- Bare out-of-book control ("capital of France" -> prefixed) refuses.
- Context: `probe-nonrelational-ask.*` (one "?" flips the model's quote at
  identical pool order), `probe-query-normalize.*` (23 x 2 sweep; quotes
  changed 4/23; pin flips 2/23 opposite; net 0).
- Everything here is single-draw except MAD answer 2 draws. Draws are a
  Stage 1 obligation, not a Stage 0 claim.

## Trigger v1 (structural only)

`canonical_query(question)` fires when ALL hold:

- no "?" anywhere, no trailing "." or "!" (sentences/highlights end with
  punctuation);
- no wh-word anywhere (`what which when where who whose why how`);
- first token not an auxiliary (`is are was were do does did can could
  should would will has have had`);
- first token not an opener/imperative/list marker (`hey hi hello please
  pls tell show give explain describe define compare contrast list types
  kinds examples difference`);
- no pronoun anywhere (`i me my mine you your we our us`).

Output: `What is <original text>?` — original casing kept. Each guard is a
closed English class, not a topic list; each gets a trigger-table unit test
in Stage 1 (including the adversarial cells: `hey can you tell me about X`,
`explain X`, `types of X`, a highlight sentence, `what is X`,
`what is X?`).

## Consumers (canonical vs raw)

| consumer | gets | note |
| --- | --- | --- |
| search embed | canonical | measured V2 shape |
| repair basis | canonical | order: canonical -> reading repair; repair keeps its score gate, canonicalization's gate is variance + pins |
| fuse dense_rank, caption_seed | canonical (via `asked`) | same string as the prompt |
| prompt | canonical | |
| anchor_words | canonical | stopword filter verified (keywords.py:34-45); prove with a unit test that `What is X?` anchors equal `X` anchors |
| simple_words | canonical | cue is a substring; survives |
| explain / quiz | raw / none | explicit gate on `ask`; quiz takes no question |

Display (readings.py precedent — the reader is shown the question they were
answered): non-refused answers append `Asked as: "<canonical>"` when R1
fired; refusals stay exactly `Not in this book.`

## Class definition and the variance metric

Equivalence classes per question: {bare, prefixed-shaped} collapse into
`What is X?` by R1. `What is X` (no "?") and filler-wrapped asks are NOT
touched by R1; their variance is measured and documented, not merged — the
punctuation-merge stays rejected (`query-normalize`: transformations loses
its pin, nonrelational gains one).

Metric: distinct behaviors — `(refused, cited chunks, figure ids)` — per
class, per mode. Target after R1: variance 1 for {bare, `What is X?`}.
Baseline captured in `probe-class-variance-2026-10-13.*`.

## Refusal deltas, pre-declared

R1 moves bare asks to question-form behavior. Recorded cases that change:
`hot warm cold data` (refuses today), `dark matter data` (bare refuses,
question form answers), IOPS (refused; retrieval never surfaces it — R1
must not change that). Sweeps carry refused baselines (answer mode
31/33/33) to re-run in Stage 1. This pairs with the recorded open decision:
refusal guardrail vs model-driven refusals.

## Stages and pass criteria

- **Stage 0 (this doc + fixture).** No engine change.
- **Stage 1 (R1).** Tests: trigger table, seam (three embeds receive the
  canonical string), anchor equivalence, explain/quiz byte-identical,
  refusal-exactness unchanged. Runs: battery both modes, recorded retest
  set, sweeps refused deltas, class-variance re-run. Pass: pins held, 0 new
  refusals on pins, variance 1 for the collapsed class, `Asked as:` shown
  only on non-refused answers where R1 fired.
- **Stage 2.** Question-type classifier as read-only audit over
  `qa-questions-overnight.json` (124) + eval sets; no behavior change.
- **Stage 3.** Per-type canonical forms one at a time (list, acronym),
  each with a pre-declared A/B.
- **Stage 4.** Show-both prompt variant (R4) — only if Stage 2/3 demand it.

## Decision log

- Module name: `canonical.py` (no collision; register in
  `tests/test_generalization.py` and the AGENTS.md module list).
- Transparency: show `Asked as:` (readings.py precedent).
- Casing: the canonical output preserves the input's case. Measured
  2026-10-13: nomic is case-blind on the probe — cos("MAD data landscape",
  "mad data landscape") = 1.0000 and the dense top-5 is identical — so the
  choice is display/semantic, not retrieval: the acronym keeps its identity
  ("MAD" is not "mad") and the echoed input is what the user typed. Case
  folding, if it ever lands, belongs in `preprocess.normalize()` on both
  sides with an index rebuild, not in `canonical_query`.
- Typography fold (curly -> ASCII in the dense `normalize`): measured by a
  full re-embed A/B, 2026-10-13 (`probe-fold-ab-2026-10-13.*`): 0/21 top-1
  flips on the pinned set; 6/21 pinned-rank deltas of ±1-2; one 14-place
  move on a typo query's pre-repair rank (the reading repair already routes
  that ask). The earlier single-run apostrophe effect (0.6752 straight /
  0.6887 curly) did not reproduce under composite-aware measurement
  (straight 0.6895, curly 0.6887, folded 0.6893). Decision: do not rebuild
  the index for the fold; bundle any future `normalize` change with the
  next book. Two corrections from the A/B: the live index is 1042 chunks
  (not 1065), and figure vectors embed caption + newline +
  referencing_paragraph, not the caption alone.
- Naming/artifacts: this family follows `artifacts/README.md` rules
  (dated names, index rows, runs promoted only by reference).

## Stage 0 results (fixture run, 2026-10-13, one draw)

40 runs, `probe-class-variance-2026-10-13-stage0.{json,log}` (the
post-Stage-1 rerun took the main name). Findings:

- **Ask mode: R1's collapse is behavior-neutral on all four questions.**
  Every bare variant already leads the same chunk and figure as
  `What is X?`. R1's ask-mode job is consistency, not repair — its
  ask-mode risk is therefore low.
- **Answer mode: MAD is the projected win.** Bare -> 3 figures + stray
  cites; `What is X?` -> 1 figure, clean. R1 collapses bare into the clean
  behavior. data mesh and watermark are already single-behavior; data
  ingestion differs only in tail citations.
- **Metric refinement before Stage 1: behavior key = (refused, lead chunk,
  figure set).** Full citation lists wobble in their tails at temperature 0
  (ingestion showed 5 distinct tails in 5 variants); the lead chunk and the
  figure set are what the user sees.
- **Flake observed:** MAD ask `What is MAD data landscape?` refused on this
  draw (it passed in `probe-prefix-rule`). The MAD ask wh-form refusal
  flake gets its own draws in Stage 1.

## Stage 1 results (landed 2026-10-13)

Landed: `canonical.py` + `answer.ask/respond(canonical=True)` + `explain`
gate (`canonical=False`) + `Asked as:` on non-refused answers; registered in
`tests/test_generalization.py` and the AGENTS.md module list.

- Tests: 210 green (16 new in `tests/test_canonical.py`: trigger table with
the adversarial cells, byte-identical pass-through, the seam — search, fuse,
caption_seed and the prompt all receive one string — refusal exactness, the
explain gate, anchor equivalence). One audit pass strengthened two fixtures:
the anchor map now carries in-bound df (a broken stopword filter fails the
test; demonstrated against a simulated filterless variant) and the explain
test asserts its highlight is trigger-eligible.
- Mutation check (`probe-test-mutations-2026-10-13.*`): five plausible
breaks — no-op canonicalization, over-firing trigger, dropped answer.py
wiring, filterless anchors, open explain gate — each turn the suite red
(10 / 18 / 2 / 1 / 1 failures); 0 survivors; suite restored green. The new
tests are falsifiable pins, not green-chasers.
- Fixture rerun vs `-stage0`: bare MAD ask follows the question-form
behavior; answer-mode bare MAD drops 3 figures to 1; mesh/watermark/
ingestion lead chunk and figures stable (ingestion tail citations stay draw
noise — the coarse key is variance-1 everywhere R1 fires).
- Retest (`probe-canonical-retest-2026-10-13.*`): zero regressions; one
intended delta — answer-mode `dark matter data` bare refusal becomes a
book-backed answer; France refuses both ways (the refusal's evidence
snippet chunk differs, noise).
- Batteries over HTTP on a fresh server (restarted for the new code): ask
PASS; answer PASS (golden 10/10, typos, probes, coherence, France).
- Residual: MAD ask wh-form refusal flake (did not recur this run);
answer-mode filler variants still diverge (Stage 2/3 territory); `Asked
as:` not yet seen in the browser window.

## Risks

- Canonicalization controls the input distribution, not the model; a bad
  uniform behavior remains a model-side problem (finetune / deterministic
  pick).
- Over-normalization loses intent; hence the guards, the audit stage, and
  never touching yes/no or comparison forms in v1.
- Single-draw evidence in the base; Stage 1 re-measures with draws.
