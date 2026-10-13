# artifacts/ — what lives here, and the rules

This directory holds evidence, harnesses, and datasets. It is **not** a dump.
Read the rules, then the index.

## Rules

1. **Scratch vs evidence.** Run outputs go to `artifacts/runs/` (gitignored).
   A run is promoted into `artifacts/` only when a document or commit
   references it by name.
2. **Names carry a date.** Any new doc or benchmark output is named
   `family-YYYY-MM-DD[-label].ext` (e.g. `eval-plain-2026-10-14-quotealign`).
   Older files keep their historical names; their dates are in this index.
3. **One live twin per family.** A benchmark family keeps the latest run plus
   any run a document names. Superseding a run means deleting the old one in
   the same commit that supersedes it (numbers folded into the doc first).
4. **Index rule.** If a tracked file here is not covered by a row below, it is
   prunable. The index is the gate.
5. **Staleness gate — future agents, read this.** Any benchmark or doc whose
   date is **two or more days old is stale**. Do not treat it as current, do
   not build on its numbers, do not "fix" code to match it. Re-run it, or
   **ask the user first**. The dated names and the dates in this index are
   how you check.
6. **Prune before docs commits.** `python artifacts/prune.py --plan` reports
   unindexed, unreferenced, over-versioned, and stale files.
7. **Deletion is recoverable.** Git history keeps everything; deleting is a
   commit, not a loss. `.git` size only grows via history (no rewrites).

Untracked files (concurrent writers' scratch, `runs/`, logs) are not indexed;
their owner decides. Files from the 2026-10-13 query-form session are
indexed in the rows below (undated probe names predate this index; the row
date is the date). `mad-ask-ceiling.md` and `query-normalization.md` are
referenced by `AGENTS.md` and remain uncommitted — the commit decision is
the user's; the index rows below keep them non-prunable meanwhile.

## Index

Dates are first-commit dates (`2026-10-11/12/13`).

### Harnesses (code, in use)

| File | What it is |
| --- | --- |
| `eval.py` | labeled-set evaluation (recall/MRR/refusals/key facts/relevance) |
| `eval-plain.py` | plain-register scorecard (imports `probe-plain.py`) |
| `step2-battery.py` | the commit-gate battery, both modes |
| `qa-sweep.py` | bulk sweep runner over `qa-questions-overnight.json` |
| `groundedness.py` | 4-gram support meter |
| `judge.py` | LLM judge (ollama default; openai wire opt-in) |
| `judge-agreement.py`, `probe-judge-scale.py` | judge calibration |
| `judge-stability.py` | verdict flip-rate probe |
| `secret-scan.py` | git-history secret scan (must stay clean) |
| `plain-edge-check.py` | contract checker over `plain-edge-*.json` |
| `probe-agentic.py`, `probe-plain.py`, `probe-llm-spell.py`, `probe-mad-phrasing.py`, `probe-codd.py`, `probe-refusal.py`, `probe-stages.py` | named probes with committed findings below |
| `probe-prefix-rule.py`, `probe-prefix-bare-terms.py`, `probe-class-variance-2026-10-13.py`, `probe-canonical-retest-2026-10-13.py`, `probe-test-mutations-2026-10-13.py`, `probe-fold-ab-2026-10-13.py`, `probe-query-normalize.py`, `probe-nonrelational-ask.py`, `probe-quote-fix.py`, `probe-plain-diagnose.py`, `probe-quote-choice.py`, `probe-mad-quote.py`, `probe-mad-seed.py`, `probe-mad-caption.py`, `probe-gloss-steer.py`, `probe-gloss-steer-control.py`, `probe-epub-links.py` | 2026-10-13 session probes (query form, quote choice, MAD ceiling, fold A/B, test mutations); findings in the rows below |
| `multihop-probe.py`, `multihop-explore.py`, `multihop-forced-keyword.py` | agentic multi-hop experiments |
| `bakeoff-digest.py` | bake-off log digester |
| `prune.py` | this directory's planner (rule 6) |
| `guard-audit.py` | guard-word audit (json next to it) |

### Datasets

| File | What it is |
| --- | --- |
| `eval-set.json` | 24 labeled items (22 answer, 2 refuse) |
| `eval-set-plain.json` | 10 plain-register items |
| `qa-questions-overnight.json` | 124 sweep questions |
| `demo-questions.md` | the demo sheet + pins (2026-10-12) |

### Evidence — current claims

| Family | What it backs | Status |
| --- | --- | --- |
| `answer-model-bakeoff-plan.md`, `answer-model-bakeoff-results.md`, `answer-model-decision.md`, `answer-model-search.md`, `ollama-quote-model-table.md` | model choice (qwen2.5:7b stays); `bakeoff-*` survivors: `bakeoff-granite4.1-3b-v2.{json,log}`, `bakeoff-side-asks.txt`, `bakeoff-side-asks-v2.txt`, `bakeoff-qwen3-4b-instruct-retries.txt`, `bakeoff-qwen3-4b-instruct-cru-retries-v2.txt` | kept (2026-10-11/12) |
| `step2-battery.{json,log}`, `step2-battery-answer.{json,log}`, `step2-battery-flaked.{json,log}` | latest battery runs + preserved cold-start flake | LIVE |
| `eval-v1*.{json,log}` | labeled-set baseline + granite/Muse replays (`eval-v1.json` is `probe-judge-scale.py` input) | kept |
| `eval-plain-*` | register history: baseline (granite/muse), v4/v4b (invalidated-run evidence), v6 (cited in AGENTS), wired/replay/quotealign/quotealign2 (post-wiring draws) | kept |
| `groundedness-authored*.*`, `groundedness-battery.*`, `groundedness-closephrase.*`, `groundedness-sweep303.*` | groundedness meter numbers in `answer-mode-overnight.md` | kept |
| `judge-grade-*`, `judge-scale-*.log`, `judge-agreement-*.log` | graded-scale and agreement findings | kept |
| `agentic-design.md`, `probe-agentic.py` | agentic prototype design + live probe | kept (2026-10-13) |
| `multihop-*` | agentic no-win evidence + forced-keyword follow-up | kept (2026-10-13) |
| `plain-edge-*.json` (17), `plain-edge-timing.txt`, `plain-edge-findings.md` | wired-register edge probes; raw responses checked by `plain-edge-check.py` | kept (2026-10-13) |
| `plain-http-{check,control}.json`, `plain-fix-check-{1,2}.json` | live route checks + fragment-fix outputs | kept (2026-10-13) |
| `plain-register-night-2026-10-13.md` | the night run report (register draws, judge drift, fixes) | kept (2026-10-13) |
| `answer-mode-overnight.md` | answer-mode overnight findings | kept (2026-10-13) |
| `mad-caption-probe.md`, `mad-phrasing-{probe.md,postrevert.txt}`, `mad-ask-ceiling.md` (untracked) | MAD retrieval history | kept (2026-10-12/13) |
| `query-canonicalization-2026-10-13.md`, `probe-class-variance-2026-10-13.{json,log}` (Stage 1 rerun), `probe-class-variance-2026-10-13-stage0.{json,log}` (baseline), `probe-canonical-retest-2026-10-13.{json,log}`, `probe-test-mutations-2026-10-13.{json,log}` (5 breaks, 0 survivors), `probe-prefix-rule.{json,log}`, `probe-prefix-bare-terms.{json,log}` | canonicalization plan + baselines + retest + test mutation check; R1 landed 2026-10-13 | kept (2026-10-13) |
| `query-normalization.md`, `probe-nonrelational-ask.*`, `probe-query-normalize.{log,json}` | one-`?` flip evidence: model-side at identical pool order; blanket punctuation strip net 0 (2/23 opposite) | kept (2026-10-13) |
| `probe-quote-fix.{json,log}`, `probe-quote-choice.log`, `probe-plain-diagnose*.{json,log}` | answer-mode quote-choice fix evidence (cited in AGENTS) | kept (2026-10-13) |
| `probe-mad-quote.*`, `probe-mad-seed.*`, `probe-mad-caption.*`, `probe-gloss-steer*.*`, `probe-epub-links.log` | MAD ask ceiling; steer #4 negative; EPUB link graph | kept (2026-10-13) |
| `probe-fold-ab-2026-10-13.{json,log}` | embedded-book typography-fold A/B (full re-embed): 0/21 top-1 flips, fold unproven -> no index rebuild; corrects figure-vector composition and the 1042-chunk count | kept (2026-10-13) |
| `how-it-works.md` | pipeline mental image | kept (2026-10-12) |
| `stage9-preprocessing.md` | preprocessing stages 5-9 | kept (2026-10-13) |
| `refusal-fixes-evidence.txt` | refusal fixes evidence | kept (2026-10-13) |
| `embedding-audit-2026-10-13.txt` | vector audit numbers | kept (2026-10-13) |
| `phase7-offline*` | wifi-off gate evidence | kept (2026-10-12) |
| `frontend-navigation-plan.md` | own-frontend direction (not approved) | kept (2026-10-13) |
| `x-research-2026-10-12.md`, `planning-context.md`, `post-v1-plan.md` | session planning notes | kept (2026-10-12) |
| `probe-plain.{json,log}`, `probe-llm-spell.{json,log}` | spell/plain probe evidence | kept (2026-10-13) |
| `guard-audit.json` | guard-word audit output | kept (2026-10-13) |
| `judge-stability-all-wired.txt` | per-question flip map | kept (2026-10-13) |
