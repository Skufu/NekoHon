# artifacts/ — what lives here, and the rules

This directory holds evidence, harnesses, and datasets. It is **not** a dump.
Read the rules, then the index.

## Where to put what (zones)

New files must land in a zone. The ~260 flat files at this level are
grandfathered history: they stay until a doc supersedes them. Do not move
them speculatively — 48 scripts hardcode `ROOT / "artifacts" / <name>`
and `sys.path` entries pointing at bare `artifacts/`; a move without a
same-commit code fix breaks the battery.

| Kind | Zone | Naming | Example |
| --- | --- | --- | --- |
| Stable runners (reused across sessions) | `artifacts/harnesses/` | stable undated name | `artifacts/harnesses/eval.py` |
| One-off probes | `artifacts/probes/` | `probe-*-YYYY-MM-DD.py`, outputs beside it | `artifacts/probes/probe-foo-2026-10-15.py` |
| Datasets, question lists | `artifacts/datasets/` | `family-YYYY-MM-DD[-label].json` | `artifacts/datasets/eval-set-2026-10-15.json` |
| Findings, decisions, plans | `artifacts/reports/` | `family-YYYY-MM-DD[-label].md` | `artifacts/reports/answer-mode-2026-10-15.md` |
| Run outputs (json/log/txt) | `artifacts/evidence/<family>/` | dated outputs, one live twin per family (rule 3) | `artifacts/evidence/eval-plain/eval-plain-2026-10-15-v7.json` |
| Scratch | `artifacts/runs/` or `artifacts/scratch/` | anything; gitignored, never indexed | `artifacts/runs/tmp-2026-10-15.log` |

New scripts resolve paths as `ROOT / "artifacts" / "<zone>" / <name>`
(not bare `artifacts/`), and any `sys.path` insert points at the zone dir
(e.g. `ROOT / "artifacts" / "harnesses"`). `prune.py` understands zone
paths; index rows cover them by full relative path
(e.g. `probes/probe-foo-2026-10-15.py`).

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
referenced by `AGENTS.md` and committed (2026-10-13).

## Index

Dates are first-commit dates (`2026-10-11/12/13`). Paths are relative to `artifacts/`.

### Harnesses (code, in use)

| File | What it is |
| --- | --- |
| `harnesses/eval.py` | labeled-set evaluation (recall/MRR/refusals/key facts/relevance) |
| `harnesses/eval-plain.py` | plain-register scorecard (imports `probe-plain.py`) |
| `harnesses/step2-battery.py` | the commit-gate battery, both modes |
| `harnesses/qa-sweep.py` | bulk sweep runner over `datasets/qa-questions-overnight.json` |
| `harnesses/groundedness.py` | 4-gram support meter |
| `harnesses/judge.py` | LLM judge (ollama default; openai wire opt-in) |
| `harnesses/judge-agreement.py`, `probes/probe-judge-scale.py` | judge calibration |
| `harnesses/judge-stability.py` | verdict flip-rate probe |
| `harnesses/secret-scan.py` | git-history secret scan (must stay clean) |
| `harnesses/plain-edge-check.py` | contract checker over `evidence/plain-edge/plain-edge-*.json` |
| `probes/probe-agentic.py`, `probes/probe-plain.py`, `probes/probe-llm-spell.py`, `probes/probe-mad-phrasing.py`, `probes/probe-codd.py`, `probes/probe-refusal.py`, `probes/probe-stages.py` | named probes with committed findings below |
| `probes/probe-prefix-rule.py`, `probes/probe-prefix-bare-terms.py`, `probes/probe-class-variance-2026-10-13.py`, `probes/probe-canonical-retest-2026-10-13.py`, `probes/probe-test-mutations-2026-10-13.py`, `probes/probe-fold-ab-2026-10-13.py`, `probes/probe-finetune-verify-2026-10-13.py`, `probes/probe-small-ask-2026-10-13.py`, `probes/probe-small-refuse-2026-10-13.py`, `probes/probe-llm-loop-2026-10-13.py`, `probes/probe-trial-queries-2026-10-14.py`, `probes/probe-contamination-2026-10-14.py`, `probes/probe-query-normalize.py`, `probes/probe-nonrelational-ask.py`, `probes/probe-quote-fix.py`, `probes/probe-plain-diagnose.py`, `probes/probe-quote-choice.py`, `probes/probe-mad-quote.py`, `probes/probe-mad-seed.py`, `probes/probe-mad-caption.py`, `probes/probe-gloss-steer.py`, `probes/probe-gloss-steer-control.py`, `probes/probe-epub-links.py` | 2026-10-13 session probes (query form, quote choice, MAD ceiling, fold A/B, test mutations, dataset verify, small-model bench); findings in the rows below |
| `probes/multihop-probe.py`, `probes/multihop-explore.py`, `probes/multihop-forced-keyword.py` | agentic multi-hop experiments |
| `probes/bakeoff-digest.py` | bake-off log digester |
| `prune.py` | this directory's planner (rule 6) |
| `harnesses/guard-audit.py` | guard-word audit (json next to it) |
| `probes/build-finetune-data-2026-10-13.py` | quote-or-refuse SFT dataset builder (teacher distillation through the shipped seam, mechanical gates) |

### Datasets

| File | What it is |
| --- | --- |
| `datasets/eval-set.json` | 24 labeled items (22 answer, 2 refuse) |
| `datasets/eval-set-plain.json` | 10 plain-register items |
| `datasets/qa-questions-overnight.json` | 124 sweep questions |
| `datasets/demo-questions.md` | the demo sheet + pins (2026-10-12) |

### Evidence — current claims

| Family | What it backs | Status |
| --- | --- | --- |
| `reports/answer-model-bakeoff-plan.md`, `reports/answer-model-bakeoff-results.md`, `reports/answer-model-decision.md`, `reports/answer-model-search.md`, `reports/ollama-quote-model-table.md` | model choice (qwen2.5:7b stays); `evidence/bakeoff/` survivors: `evidence/bakeoff/bakeoff-granite4.1-3b-v2.{json,log}`, `evidence/bakeoff/bakeoff-side-asks.txt`, `evidence/bakeoff/bakeoff-side-asks-v2.txt`, `evidence/bakeoff/bakeoff-qwen3-4b-instruct-retries.txt`, `evidence/bakeoff/bakeoff-qwen3-4b-instruct-cru-retries-v2.txt` | kept (2026-10-11/12) |
| `evidence/step2-battery/step2-battery.{json,log}`, `evidence/step2-battery/step2-battery-answer.{json,log}`, `evidence/step2-battery/step2-battery-flaked.{json,log}` | latest battery runs + preserved cold-start flake | LIVE |
| `evidence/eval-v1/eval-v1*.{json,log}` | labeled-set baseline + granite/Muse replays (`eval-v1.json` is `probe-judge-scale.py` input) | kept |
| `evidence/eval-plain/eval-plain-*` | register history: baseline (granite/muse), v4/v4b (invalidated-run evidence), v6 (cited in AGENTS), wired/replay/quotealign/quotealign2 (post-wiring draws) | kept |
| `evidence/groundedness/groundedness-authored*.*`, `evidence/groundedness/groundedness-battery.*`, `evidence/groundedness/groundedness-closephrase.*`, `evidence/groundedness/groundedness-sweep303.*` | groundedness meter numbers in `answer-mode-overnight.md` | kept |
| `evidence/judge-grade/judge-grade-*`, `evidence/judge-scale/judge-scale-*.log`, `evidence/judge-agreement/judge-agreement-*.log` | graded-scale and agreement findings | kept |
| `reports/agentic-design.md`, `probes/probe-agentic.py` | agentic prototype design + live probe | kept (2026-10-13) |
| `evidence/multihop/multihop-*` | agentic no-win evidence + forced-keyword follow-up | kept (2026-10-13) |
| `evidence/plain-edge/plain-edge-*.json` (17), `evidence/plain-edge/plain-edge-timing.txt`, `reports/plain-edge-findings.md` | wired-register edge probes; raw responses checked by `plain-edge-check.py` | kept (2026-10-13) |
| `evidence/plain-http/plain-http-{check,control}.json`, `evidence/plain-fix-check/plain-fix-check-{1,2}.json` | live route checks + fragment-fix outputs | kept (2026-10-13) |
| `reports/plain-register-night-2026-10-13.md` | the night run report (register draws, judge drift, fixes) | kept (2026-10-13) |
| `reports/answer-mode-overnight.md` | answer-mode overnight findings | kept (2026-10-13) |
| `reports/mad-caption-probe.md`, `reports/mad-phrasing-probe.md`, `evidence/mad-phrasing/mad-phrasing-postrevert.txt`, `reports/mad-ask-ceiling.md` (untracked) | MAD retrieval history | kept (2026-10-12/13) |
| `reports/query-canonicalization-2026-10-13.md`, `evidence/probe-class-variance/probe-class-variance-2026-10-13.{json,log}` (Stage 1 rerun), `evidence/probe-class-variance/probe-class-variance-2026-10-13-stage0.{json,log}` (baseline), `evidence/probe-canonical-retest/probe-canonical-retest-2026-10-13.{json,log}`, `evidence/probe-test-mutations/probe-test-mutations-2026-10-13.{json,log}` (5 breaks, 0 survivors), `evidence/probe-prefix-rule/probe-prefix-rule.{json,log}`, `evidence/probe-prefix-bare-terms/probe-prefix-bare-terms.{json,log}` | canonicalization plan + baselines + retest + test mutation check; R1 landed 2026-10-13 | kept (2026-10-13) |
| `reports/query-normalization.md`, `evidence/probe-nonrelational-ask/probe-nonrelational-ask.*`, `evidence/probe-query-normalize/probe-query-normalize.{log,json}` | one-`?` flip evidence: model-side at identical pool order; blanket punctuation strip net 0 (2/23 opposite) | kept (2026-10-13) |
| `evidence/probe-quote-fix/probe-quote-fix.{json,log}`, `evidence/probe-quote-choice/probe-quote-choice.log`, `evidence/probe-plain-diagnose/probe-plain-diagnose*.{json,log}` | answer-mode quote-choice fix evidence (cited in AGENTS) | kept (2026-10-13) |
| `evidence/probe-mad-quote/probe-mad-quote.*`, `evidence/probe-mad-seed/probe-mad-seed.*`, `evidence/probe-mad-caption/probe-mad-caption.*`, `evidence/probe-gloss-steer/probe-gloss-steer*.*`, `evidence/probe-epub-links/probe-epub-links.log` | MAD ask ceiling; steer #4 negative; EPUB link graph | kept (2026-10-13) |
| `evidence/probe-fold-ab/probe-fold-ab-2026-10-13.{json,log}` | embedded-book typography-fold A/B (full re-embed): 0/21 top-1 flips, fold unproven -> no index rebuild; corrects figure-vector composition and the 1042-chunk count | kept (2026-10-13) |
| `reports/finetune-data-prep-2026-10-13.md`, `reports/finetune-loop-eval-2026-10-13.md`, `reports/finetune-colab-recipe-2026-10-13.md`, `reports/finetune-colab-2026-10-13.ipynb`, `evidence/probe-finetune-verify/probe-finetune-verify-2026-10-13.{json,log}`, `evidence/probe-small-ask/probe-small-ask-2026-10-13*.{json,log}`, `evidence/probe-small-refuse/probe-small-refuse-2026-10-13*.{json,log}`, `evidence/probe-llm-loop/probe-llm-loop-2026-10-13.*.log` | quote-or-refuse dataset + ratio variants (train x3 194 / x2 167 / x1 140, bench 45; verifier PASS each); x3 checkpoints: refusals fixed on both, 3B loops on some answers (draw-process measured, sampler fixes rejected), Qwen3 parked; Colab recipe v4 (two ratios, one session) | kept (2026-10-13) |
| `reports/x2-trial-2026-10-14.md`, `evidence/probe-trial-queries/probe-trial-queries-2026-10-14.{json,log}`, `evidence/probe-contamination/probe-contamination-2026-10-14.{json,log}` | smallbook_x2 live trial: fragment-pattern results vs the 7B (3 false-refusal classes grounded; engine backlog logged); contamination audit (0 exact, 4 bench near-twins in train); x2 = app trial default | kept (2026-10-14) |
| `reports/loop-mechanism-analysis-2026-10-14.md` (sources: `evidence/probe-fragment/probe-fragment-2026-10-14.model-smallbook_x2.{json,log}`, `.model-qwen2.5-7b.*`) | x2 loop forensics: the File Formats transcript is a context recital with zero n-gram repetition, EOS is a near-tie at a passage boundary (suite 10/10 length-stops; one fresh-load live run stopped at 243 tokens); template/stops identical to qwen2.5:7b; sampler fixes stay rejected; x2c/q8 gate hygiene + engine num_predict cap proposed | kept (2026-10-14) |
| `reports/finetune-expert-review-2026-10-14.md`, `reports/eval-harness-audit-2026-10-14.md`, `reports/finetune-dataset-verification-2026-10-14.md`, `reports/judge-status-2026-10-14.md`, `evidence/user-query-probes-2026-10-14.md` | 2026-10-14 pre-run review batch: x2c swaps corrected and rebuilt (24 swaps, hash 27a84899, re-verified PASS, contamination 0 exact / 11 pairs), equal-draws + q8 + seed-control gate amendments, muse relay re-verified live (outside the gate), raw user query-test log | kept (2026-10-14) |
| `evidence/step2-battery/step2-battery-revert-rehearsal-2026-10-14.{json,log}`, `evidence/step2-battery/start-revert-rehearsal-2026-10-14.bat` | gate item 6 rehearsal: the `ANSWER_MODEL=qwen2.5:7b` env seam starts the server and passes the battery once (golden 10/10, typos/probes/France PASS); default engine restored after | kept (2026-10-14) |
| `evidence/x2c-session-2026-10-14/run-log-smallbook_x2c.json`, `run-log-smallbook_x2_seed1234.json`; `evidence/probe-fragment/probe-fragment-2026-10-14.model-{smallbook_x2c,smallbook_x2c_q8,smallbook_x2_seed1234}.{json,log}`; `evidence/probe-small-ask/probe-small-ask-2026-10-13.model-smallbook_x2c{,q8}*.{json,log}`; `evidence/probe-small-refuse/probe-small-refuse-2026-10-13.model-smallbook_x2c{,q8}*.log`; same `…model-smallbook_x2_seed1234*.log`; `evidence/probe-llm-loop/probe-llm-loop-2026-10-13.{x2c,x2-seed1234,x2c-q8}-battery-sweep5.log`, `evidence/probe-trial-queries/probe-trial-queries-2026-10-14.model-smallbook_x2c{,q8}.{json,log}` | x2c session (A100): Colab run-logs + every gate probe; verdict in `reports/x2-trial-2026-10-14.md` (not adopted — suite bar vs 7B; seed control diverged; q8 quant effect measured) | kept (2026-10-14) |
| `reports/how-it-works.md` | pipeline mental image | kept (2026-10-12) |
| `reports/system-map-2026-10-13.md` | pipeline map; the mermaid example `AGENTS.md` points at | kept (2026-10-13) |
| `reports/stage9-preprocessing.md` | preprocessing stages 5-9 | kept (2026-10-13) |
| `evidence/refusal-fixes-evidence/refusal-fixes-evidence.txt` | refusal fixes evidence | kept (2026-10-13) |
| `evidence/embedding-audit/embedding-audit-2026-10-13.txt` | vector audit numbers | kept (2026-10-13) |
| `evidence/phase7-offline/phase7-offline*` | wifi-off gate evidence | kept (2026-10-12) |
| `reports/frontend-navigation-plan.md` | own-frontend direction (not approved) | kept (2026-10-13) |
| `reports/golden-growth-plan-2026-10-13.md` | labeled-set growth plan: statistical targets (24 -> ~100), strata, book-first labeling protocol, 4-batch rollout (not approved) | kept (2026-10-13) |
| `reports/x-research-2026-10-12.md`, `reports/planning-context.md`, `reports/post-v1-plan.md` | session planning notes | kept (2026-10-12) |
| `evidence/probe-plain/probe-plain.{json,log}`, `evidence/probe-llm-spell/probe-llm-spell.{json,log}` | spell/plain probe evidence | kept (2026-10-13) |
| `evidence/guard-audit/guard-audit.json` | guard-word audit output | kept (2026-10-13) |
| `evidence/judge-stability/judge-stability-all-wired.txt` | per-question flip map | kept (2026-10-13) |
| `reports/x2d-forms-2026-10-14.md`, `probes/gen-x2d-forms-2026-10-14.py` | x2d step 1 run: v1 66 forms; v2 widening (same doc) **171 forms** (swap 24 / bare 38 / restate 32 / explain 27 / heading 25 / greet 23 / named 2) through suite + bench + retrieval preflight; projected dataset 338 rows, 254 steps; output `data/finetune/x2d-forms-2026-10-14.json` | kept (2026-10-14) |
| `reports/x2d-plan-2026-10-14.md`, `reports/x2d-refusal-mining-2026-10-14.md`, `reports/x2d-builder-notes-2026-10-14.md`, `reports/x2d-plan-audit-2026-10-14.md`, `reports/gate-driver-notes-2026-10-14.md`, `datasets/sealed-forms.json`, `evidence/finetune-data-prep/*-x2d.{json,log}`, `harnesses/run-gate.py`, `probes/mine-x2d-refusals-2026-10-14.py`, `probes/build-finetune-x2d-2026-10-14.py` | x2d build run (2026-10-14): 27 new refusals (54 unique union), teacher capture -> **373 rows kept / 328 train (274 answer + 54 refusal)**, bench byte-identical (`174afd18…`), verifier PASS, contamination 0 exact / 13 pairs, seal clean, manifest, notebook v7 (`EXPECTED_X2D=328`), gate driver smoke-tested; Colab slot pending | kept (2026-10-14) |
| `evidence/x2d-session-2026-10-14/run-log-smallbook_x2d.json`, `evidence/probe-fragment/probe-fragment-2026-10-14.model-smallbook_x2d{,_q8}.{json,log}`, `evidence/probe-small-ask/probe-small-ask-2026-10-13.model-smallbook_x2d*.{json,log}`, `…model-x2d-q8.run*.*`, `evidence/probe-small-refuse/probe-small-refuse-2026-10-13.model-smallbook_x2d.run*.log`, `evidence/probe-trial-queries/probe-trial-queries-2026-10-14.model-smallbook_x2d.{json,log}`, `evidence/probe-llm-loop/probe-llm-loop-2026-10-13.smallbook_x2d-battery-sweep5.log` | x2d gate session: battery **20/21 (best recorded)** + source-systems/ETL pin-misses fixed, refusals 10/10, loops 0; suite-citing classes still under the 7B bar (uncited prose on unseen forms) — not adopted under gate item 2; verdict in `reports/x2d-plan-2026-10-14.md` | kept (2026-10-14) |
| `reports/second-book-2026-10-14.md`, `probes/probe-second-book-2026-10-14.py`, `evidence/probe-second-book/probe-second-book-2026-10-14.{json,log}` | second-book portability probe ("Quantization and Fast Inference", 506 chunks / 0 figures, `data/index.quantbook.json`): refusal boundary transfers (0 false refusals, controls exact), citations do not (2/11 non-control answers tagged; `chapter-N` chapter strings suspected); 7B France hallucination with a fabricated pin; figure path untested | kept (2026-10-14) |
| `reports/retry-safety-net-2026-10-14.md`, `evidence/probe-fragment/probe-fragment-2026-10-14.model-smallbook_x2{,d}{,.gate}.{json,log}`, `evidence/probe-trial-queries/probe-trial-queries-2026-10-14.model-smallbook_x2d{,.gate}.{json,log}`, `evidence/probe-second-book/probe-second-book-2026-10-14.retry.{json,log}` | validation-gated `[Ch. ` retry landed in `answer.py` (x2d verdict option c): uncited answer-mode replies are retried once and kept only on a verbatim-quote citation; suite at 10 draws x2 60->111/160, x2d 21->111/160 (x2d 0 loops, x2 20); x2d still short of gate item 2 (bare 41/50, order 20/40); visible-ten uncited three not rescued; second book rescued 2/10 (x2) and 1/10 (x2d) | kept (2026-10-14) |
