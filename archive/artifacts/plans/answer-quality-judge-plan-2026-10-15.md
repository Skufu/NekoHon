# Answer-quality judge — ranking the content itself (2026-10-15)

Status: draft — awaiting the owner's yes on decisions A/B below.

Trigger: the owner sees non-standard outputs in the window ("I don't like the
outputs we are getting") and there is no per-answer quality evaluation to rank
or triage them.

## The gap this closes

What exists today (all boolean; none of it ranks an answer):

- `judge.py` — relevance per passage, key-fact rescue, fidelity gate, example
  dial; one-word verdicts; unvalidated vs human labels.
- `eval.py` / `eval-plain.py` — mechanical ranks (recall/MRR/precision) and
  scorecards; the judge only flips a boolean or two.
- `probe-judge-scale.py` — a 0–3 graded relevance scale, parked, never wired in.

What is missing:

1. A rubric for the *answer itself* — responsive / complete / form, not just
   grounded.
2. A per-answer harness that ranks worst-first and says why (defect label).
3. Owner labels — the only ground truth for "standard". Without them every
   judged number stays unvalidated.
4. A pre-registered agreement bar and a stability check before any judged
   number drives a decision.

## The bar we judge against

- `prompt.py` SYSTEM / SYSTEM_ANSWER shapes: quote first + `[Ch. N]` tags +
  one gloss line; refusal exactly `Not in this book.`
- `GOAL.md`: a true answer, an honest refusal, a citation the reader can
  check; an answer that reads as broken is a failure.
- The question's own subject must appear in the answer (the coherence class
  the battery and the sweep already probe mechanically).

## Rubric v0 (frozen before the first run; per answer)

One-word verdicts, same pattern as today's judge (strict retry, temp 0):

- `responsive` 0–3 — does it answer the question that was asked.
- `complete` 0–3 — carries the key fact / the asked-for list.
- `form` 0–3 — output-contract shape; no filler, recitation, or hedging.
- `grounded` supported/unsupported — reuse of the existing fidelity verdict.
- `defect` one of `wrong-subject`, `wrong-asked-form` (query shape mangled
  before retrieval), `incomplete-list` (a "what are" that doesn't list),
  `incomplete-comparison` (a "vs" answered one-sided — found in the checker
  pass 2026-10-15), `false-refusal`, `uncited`, `recitation-loop`,
  `filler-hedge`, `format-drift`, `invented-claim`, `overlong`, `none` —
  plus a ≤12-word reason.

No blended score (repo convention: separate metrics, no F1 — one number hides
which side failed).

Ranking rule (triage order, not a metric): `grounded=unsupported` first, then
`defect≠none`, then `responsive` asc, `complete` asc, `form` asc; ties keep
input order. The worst-first list is the output the owner reads.

## Calibration — the missing ground truth

- Sample: `artifacts/datasets/owner-rated-2026-10-15.jsonl` — 24 rows
  (`question`, `answer`, `owner_rating` good/mixed/bad, `owner_note`). Seed
  candidates: the owner's window session (2026-10-15), the visible-ten uncited
  three, the sweep's incoherent rows, plus good answers for contrast. Never
  trained; visible, not sealed.
- v0 bar, written before any run: every `bad` row (owner, else persona)
  ranks above every `good` row in the worst-first list; `grounded` + `defect`
  agree with the rater's note on ≥ 90% of the sample.
- Stability: 3 draws per item (`judge-stability.py`) before judged numbers are
  reported as trends.
- Until the bar holds, judged numbers are dials only; commit gates stay
  mechanical.

## Harness

`artifacts/harnesses/rank-answers.py` (new runner):

- questions from a dataset (`--set`), or `--live` against the server on :8000;
- answers collected the way `eval.py` / `groundedness.py` do (the same code
  path as the server, in-process, temp 0), `--mode answer|ask`;
- judges each answer (extended `judge.py`: `judge_answer_axis`,
  `judge_defect`; ~5 calls per answer);
- writes `artifacts/evidence/answer-quality/answer-quality-<label>-<judge-slug>.{json,log}`;
  the log is the worst-first table + judge identity + the UNVALIDATED banner.

Cross-check: the mechanical twin stays `groundedness.py` (4-gram support) —
judged `grounded` vs measured support on the same answers is a judge-vs-meter
agreement reading that needs no extra labels.

## Routing (a finding that ends nowhere would make this a scoreboard)

- `wrong-subject` / `recitation-loop` / `filler-hedge` / `format-drift` →
  `prompt.py` / engine lane;
- `uncited` / `false-refusal` → training-list classes (existing build recipe);
- `invented-claim` → answer-mode retry/prompt lane (the quote strip only
  covers ask mode);
- `complete` low with `grounded` high → retrieval/selection lane.

## Calibration log (2026-10-15)

Harness built (`harnesses/rank-answers.py`; parse pins in
`tests/test_judge_axes.py`; 246 tests OK). Three calibration runs on the
sample, judge `openai:muse-spark-1.3-contributor`:

| run | prompt change | persona agreement | bads caught | v0 bar |
| --- | --- | --- | --- | --- |
| v1 | rubric as drafted | 16/24 | 2/3 | FAIL |
| v2 | gloss-restatement is not recitation/filler; disclosures are not defects; fragment quotes stay grounded; brief-correct = 3 | **19/24** | 3/3 | FAIL |
| v3 | the same gloss clause added to the defect prompt | 16/24 | 2/3 | FAIL |

Verdict: **v3 regressed and was reverted the same day** — the prompts stand
at v2 wording. Across the three runs the same rows flip: `ddr4 vs ddr5`
false-refusal missed/caught/missed; `multicloud` clean/clean/wrong-asked-form;
`Database` recitation/format-drift/none. Prompt sensitivity plus apparent
judge instability; the stability requirement is not met, so judged numbers
stay dials. Next: `judge-stability.py` n=3 over the sample rows before any
further rubric tuning. Contested rows for owner arbitration: `Data` (#4 —
false-refusal in all three runs, persona says good), `Location` (#11),
`MAD` (#19), `atermark` (#21).

Evidence:
`evidence/answer-quality/answer-quality-owner-sample{,-v2,-v3}-openai-muse-spark-1-3-contributor.{json,log}`.

## Rating method v2 — proposed 2026-10-15 (owner: "we need better rating")

The lesson from the three calibration runs: nobody — owner, persona, or judge
— rates a single answer 0–3 reliably. In our own runs the binary fidelity
verdict stayed near-stable while the 12-way defect label flipped between
runs. So stop rating single answers on scales; rate checkables and
differences.

**Layer 1 — checkables (machine, zero variance).** Every sample row gets the
pins the eval set already uses: `expect` (answer/refuse), `gold_chunks`,
`key_fact`. Rating = refusal correct, gold cited, key fact present, quote
verbatim. Deterministic; catches refusals, missing citations, missing facts.

**Layer 2 — yes/no bits, voted.** Only for feel-quality: (a) does it answer
the question asked; (b) is every sentence supported by the shown passages;
(c) is it a clean quote-plus-gloss; (d) would a reader need to re-ask. Each
bit asked three times, majority decides; a defect label derives from the bit
that failed, not from a 12-way menu in one shot. Kills the flip noise by
construction; the three votes are the cost.

**Layer 3 — pairwise for builds.** A new model is never scored alone: old vs
new answers to the same questions, judge picks better/tie, three votes —
that is how "is the next finetune better" gets answered, the only question
the next build actually asks.

**Anchor — gold answers.** For 10–15 core questions the teacher drafts the
ideal answer; the owner approves a handful. Rating can then be partly "does
the answer carry the gold facts" — near ground truth without a rating
sitting. Owner's remaining job: approve gold pins on ~10 rows + arbitrate
near-ties; minutes.

Sequence: (1) fill pins for the 27 sample rows from the record; (2) rewire
`rank-answers.py` to layers 1–2 and re-run — report the flip-rate drop;
(3) pairwise mode before the next build comparison.

The 0–3 axes and single-shot defect scores are dropped as scores; the
worst-first triage list stays, built from checkables + failed bits.

Result (2026-10-15): pins filled for all 27 rows; harness rewired; two
identical runs (`owner-sample-m2a`, `-m2b`). The checkables were
deterministic as designed — both recorded false refusals caught by pins
(`ddr4 vs ddr5`, `why's kafka so popular?`), missing key facts stable on
#24/#26, gold cites present. Between the two runs: 3 of 27 rows changed
verdict (#1, #9, #11 — single bits flipping 2–1); raw vote lists differed
on 10 row-bit pairs while majorities held; persona agreement 20/24 in BOTH
runs (it was 16 → 19 → 16 across the scale era). Not zero — the honest
number is 3 borderline rows; no further tuning without a reason.

Checker correction (recorded): #7's stored `quote_ok=False` was a harness
false positive — a naive fold+substring check where the engine's own
matcher (`answer._quote_in_passage`) handles figure refs and punctuation
variants. Fixed by using the engine matcher; the offline recheck corrects
only #7 (False -> True; its derived defect becomes `incomplete` via the
no-reask bit). The m2a/m2b files predate the fix and carry the stale #7
field; this paragraph is the correction of record.

## Next-run duties (owner direction 2026-10-15)

- **Next gate run** (any model): `rank-answers.py` runs over the sample and
  the visible ten; its worst-first list attaches to the gate report as dials.
  Gates stay mechanical; a judged column never decides a pass.
- **Next finetune build**: the build report carries a judged before/after on
  its target classes (previous model vs candidate), same rubric, judge
  identity recorded.
- **Capture pre-screen (optional, visible rows only)**: fidelity + key-fact
  verdicts over captured rows as a build aid; sealed items are never judged
  here (and never trained).
- Promotion of judged metrics from dial to gate happens only by owner
  decision after the v0 bar holds.

## Sequence

1. Owner seeds and rates the 24-row sample (one sitting) — the blocking input.
2. Extend `judge.py` + tests (parsing only; no network in tests).
3. Build `rank-answers.py`; run it over the owner sample; report agreement
   against the v0 bar.
4. If the bar holds: run over `qa-questions-overnight.json` + the visible ten;
   publish the worst-first list; route the findings to the lanes above.
5. Dated report + verdict; update this plan's status.

## Cost / privacy

N × ~5 judge calls on the default muse-spark relay (or `JUDGE_BACKEND=ollama`
offline). Engine and server untouched.

## Non-goals

No shipped cloud judging; no judged commit gate; no blended score;
owner-rated rows are never trained; not a model-vs-model bake-off (that stays
the battery's job).

## Owner rating scale (decided 2026-10-15) — the reader's words

Rate each row in the order a reader actually reads:

1. Did it answer the thing I asked?
2. Did I get the information I came for (the fact, list, or definition)?
3. Can I see where it came from, and does it check out?
4. Does it read right — no filler, no recitation, not broken?
5. Would I have to re-ask or go elsewhere?

- `good` — got what I came for; trust it; no digging needed.
- `mixed` — it answered something, but it's off (emphasis, filler, clunky,
  or needs double-checking).
- `bad` — not what I'd want to see: doesn't answer, misleads, reads broken,
  or refuses when it shouldn't.

Rule of thumb: `bad` if 1/2 fails or 5 is yes; `mixed` if 3/4 wobble; else
`good`. A `note` is required for `mixed`/`bad` — in the owner's words; that
note is the ground truth the judge is scored against.

## Roles

- **Owner** — overrides everything: delegated the rating seat 2026-10-15
  ("not my forte"); may flip any row at any time.
- **Persona rater** (delegated agent, briefed with
  `reports/owner-pattern-2026-10-15.md`) — stands in for the owner on the
  sample; labels live as `persona_rating`/`persona_note` in the dataset and
  are a weaker claim than owner labels, stated as such wherever reported.
- **Judge** (`muse-spark-1.3-contributor`) — automated rater; unvalidated
  until the bar holds.
- **Checker** (the agent) — pre-pass stored (`checker_rating`/`checker_note`);
  audits every rater-vs-judge disagreement after the calibration run. The
  rubric changes only at a version boundary (v1 -> v2) with the reason
  recorded.

## Sample status (2026-10-15)

Captured: `artifacts/datasets/owner-rated-2026-10-15.jsonl` — 24 rows from
the live engine (answer mode, temp 0, one draw; 4 refusals in the mix:
`Data`, `ddr4 vs ddr5`, `why's kafka so popular?`, `France`). `rating`/`note`
are null, awaiting the owner. Seed mix: owner session 5, sweep-incoherent 5,
known failures 5, battery classics 4, edge/typo/refusal 3, capture forms 2.

Checker's first read of the capture (to argue with, not to trust): `Location`
answered from a streaming-locations passage (wrong sense of the term),
`ddr4 vs ddr5` refused today though it was answered-but-uncited on
2026-10-14 (behavior moved), `MAD data landscape` opens on "It's hard."
