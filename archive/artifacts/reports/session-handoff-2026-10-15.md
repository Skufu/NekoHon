# Session handoff — answer-quality lane, what we did + concerns (2026-10-15)

**Read first**: another agent is mid-churn ("the bloodbath"). My lane is
frozen at `artifacts/runs/snapshot-2026-10-15-answer-quality/` — diff the
live files against that folder before resuming anything.

## What we did (all measured, in order)

1. **Judge default flipped** to `muse-spark-1.3-contributor` (cloud, OpenCode
   relay) per owner direction; `granite4.1:8b` demoted to the offline revert
   (`JUDGE_BACKEND=ollama`). GOAL.md + AGENTS hard rules amended; judge.py,
   eval.py, eval-plain.py, READMEs updated.
2. **Blank-pane failure class fixed** (two occurrences: micro-partitioning,
   the typo'd "Dataa…" ask): client guard in `web/lib/engine.ts` + the
   engine's stream contract now always ends with `final` or `error`
   (`server.py` catch-all). Not yet live: needs an engine restart; no
   recurrence observed since, so the guards are untested in the wild.
3. **Rating system built and calibrated** (the long thread):
   - `artifacts/harnesses/judge.py` — rubric + voted yes/no bits.
   - `artifacts/harnesses/rank-answers.py` — worst-first ranking, evidence
     files, rater agreement, UNVALIDATED banner.
   - Scale era (v1→v2→v3): persona agreement 16 → 19 → 16/24; v3 reverted.
   - Method v2 (checkables + 4 bits voted ×3): two identical runs — 3 of 27
     rows wobbled (single 2–1 vote flips: #1, #9, #11); persona agreement
     20/24 in BOTH runs; checkables deterministic — both recorded false
     refusals caught (ddr4, kafka), missing content caught (#24, #26).
4. **The 27-row owner sample** (`artifacts/datasets/owner-rated-2026-10-15.jsonl`)
   with machine pins, owner labels on rows 25–27, persona + checker ratings
   on 1–24; mined owner-pattern brief in `artifacts/reports/owner-pattern-2026-10-15.md`.
5. **Query-rewriter plan drafted** (`artifacts/plans/query-rewriter-plan-2026-10-15.md`):
   vs-form (monolith finding), list-shape (OSS finding), deterministic layer 0 +
   gated local-LLM layer 1. Not built.
6. **My own harness error found and fixed**: #7's "quote not verbatim" was my
   naive matcher; switched to the engine's `answer._quote_in_passage`; offline
   recheck confirms the correction. Recorded in the plan.

## Concerns (ranked)

1. **The judge wobbles 3/27.** It is a triage dial, not a scoreboard. No
   future flow may treat judged numbers as a gate without a new decision.
2. **Real owner labels exist on 3 rows only.** Everything else is
   persona/checker stand-ins; every agreement claim is against stand-ins,
   and the persona itself is an LLM. If calibration quality matters, the
   owner's minutes are still the bottleneck.
3. **The blank-pane fix is untested live** (restart pending). Until it
   recurs with the guards active, the failure class is "fixed in code", not
   "verified gone".
4. **Open items the judge found, none fixed**: false refusals
   (`ddr4 vs ddr5`, `why's kafka so popular?`), the vs-question form, the
   list-shape rule, the OSS/monolith findings. Plans exist; code doesn't.
5. **Contamination discipline**: the 27-row sample must never enter
   training; sealed items were not touched; the sample is visible, not
   sealed.
6. **Cloud judge economics/privacy**: eval runs now call the relay by
   default (network + key). Offline revert documented. Shipping a cloud
   judge anywhere needs its own yes.
7. **Shared-file churn**: `artifacts/README.md` and `artifacts/plans/README.md`
   are being edited by the other agent; my index rows may be overwritten.
   The snapshot is the reference; re-add rows after the bloodbath if lost.
8. **Missing piece for the next finetune**: pairwise compare (old vs new
   model answers) is designed but not built — without it, the next build
   gets only the mechanical gates.

## Where everything lives

- Plan + calibration log: `artifacts/plans/answer-quality-judge-plan-2026-10-15.md`
- Rewriter plan: `artifacts/plans/query-rewriter-plan-2026-10-15.md`
- Code: `artifacts/harnesses/judge.py`, `artifacts/harnesses/rank-answers.py`,
  `tests/test_judge_axes.py`
- Sample: `artifacts/datasets/owner-rated-2026-10-15.jsonl`
- Evidence: `artifacts/evidence/answer-quality/` (v1–v3, m2a, m2b)
- Brief: `artifacts/reports/owner-pattern-2026-10-15.md`
- Frozen copy: `artifacts/runs/snapshot-2026-10-15-answer-quality/`

## Decisions waiting for the owner (when back)

1. Diff the bloodbath against the snapshot: keep / merge / revert the lane.
2. Build pair-compare now (bridges to the next finetune), or wait.
3. Arbitrate the contested rows (#4 Data, #11 Location, #19 MAD, #21
   atermark) and the 3 wobble rows (#1, #9, #11) — one word each, or leave
   as the known noise floor.
4. After reading the bloodbath's new plans (`refusal-ux`, `distill-*`,
   `gap-to-goal`, …): decide whether the judge plugs into them or pivots.
