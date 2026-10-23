# artifacts/

Live measuring tools, their datasets, and forward-looking plans. Dated reports,
raw evidence, one-off probes and superseded plans are history: they live in
`../archive/`, never edited, tested or imported.

## Rules

1. Run output goes to `runs/` or `scratch/` (both gitignored). Promote a run
   only when a document names it, and index it here.
2. New files carry their date in the name: `family-YYYY-MM-DD[-label].ext`.
   Reusable runners keep a stable undated name.
3. One live twin per family: the latest run plus any run a document names.
4. Every tracked file below `artifacts/` needs a row in the index. The index is
   the gate: `python3 artifacts/prune.py --plan` must report 0 unindexed and 0
   missing.
5. A benchmark or document dated two or more days ago is stale. Re-run it before
   building on it.
6. Judge calls (the cloud judge) are an eval-only exception to the local-only
   rule. The engine, server and batteries never use them.

`prune.py` is read-only. Flags: `--plan` (print the plan), `--stale-days N`
(default 2).

## Index

Paths are relative to `artifacts/`. "Engine" means a running `engine.server` on
:8000; "Ollama" means the local models are installed and serving; "judge" means
the judge backend is configured (`JUDGE_BACKEND`, key in `.judge-key`, see
`harnesses/judge.py`).

### Harnesses

| File | What it is | Needs |
| --- | --- | --- |
| `harnesses/step2-battery.py` | The commit-gate battery: golden questions with pinned chunks, typo probes, coherence probes, France refusal. `BATTERY_MODE=answer` runs answer mode. | Engine, Ollama |
| `harnesses/hard-bench.py` | Hard-question benchmark over `datasets/hard-bench-2026-10-17.jsonl`. | Ollama (in-process) |
| `harnesses/qa-sweep.py` | Bulk question sweep over `datasets/qa-questions-overnight.json` with refusal classification. `SWEEP_MODE=answer` for answer mode. | Engine, Ollama |
| `harnesses/groundedness.py` | 4-gram support meter: the share of answer sentences supported by the shown passages. | Ollama (in-process) |
| `harnesses/adrian-eval.py` | Multi-turn conversational scenarios (highlights, follow-ups, adversarial edges) from `datasets/adrian-realworld-eval-2026-10-17.json`. | Engine, Ollama |
| `harnesses/crossbook-evil-eval.py` | Cross-book multi-turn scenarios from `datasets/crossbook-evil-eval-2026-10-18.json`. Needs the books it names to be ingested. | Engine, Ollama |
| `harnesses/probe-highlight-2026-10-16.py` | Runs the held-out highlight golden set (`datasets/highlight-golden-2026-10-16.jsonl`) against one or more model tags. | Ollama (in-process) |
| `harnesses/probe-test-mutations-2026-10-13.py` | Mutation check: breaks canonicalization in memory five ways; the suite must go red each time. | none |
| `harnesses/eval.py` | Labeled-set evaluation (recall, MRR, refusals, key facts, relevance) over `datasets/eval-set.json`. | Ollama, judge |
| `harnesses/eval-plain.py` | Plain-words register scorecard over `datasets/eval-set-plain.json` (imports `harnesses/probe-plain.py`). | Ollama, judge |
| `harnesses/probe-plain.py` | Plain-register probe used by the scorecard. | Ollama (in-process) |
| `harnesses/plain-edge-check.py` | Contract checker for saved plain-register edge responses. | none |
| `harnesses/rank-answers.py` | Answer-quality ranking: machine checks plus yes/no bits voted three times; worst-first triage, never a gate. | Ollama, judge |
| `harnesses/judge.py` | The judge client (default cloud `muse-spark-1.3-contributor`; `JUDGE_BACKEND=ollama` uses local `granite4.1:8b`). | judge or Ollama |
| `harnesses/judge-agreement.py` | Agreement between two saved judged runs. | none |
| `harnesses/judge-stability.py` | Verdict flip-rate probe for one judged item. | Ollama, judge |
| `harnesses/secret-scan.py` | Scans git history and the tracked tree for credentials; must exit 0. | none |

### Datasets

| File | What it is |
| --- | --- |
| `datasets/eval-set.json` | Labeled questions for `harnesses/eval.py`. |
| `datasets/eval-set-plain.json` | Questions for the plain-register scorecard. |
| `datasets/qa-questions-overnight.json` | Sweep and groundedness question set. |
| `datasets/hard-bench-2026-10-17.jsonl` | Hard-question benchmark items with pins. |
| `datasets/highlight-golden-2026-10-16.jsonl` | 24 held-out highlight cases, pinned by `tests/test_highlight_golden.py`. |
| `datasets/highlight-train-2026-10-16.jsonl` | Highlight training rows kept as the golden set's counterpart. |
| `datasets/adrian-realworld-eval-2026-10-17.json` | Multi-turn scenarios for `harnesses/adrian-eval.py`. |
| `datasets/crossbook-evil-eval-2026-10-18.json` | Cross-book scenarios for `harnesses/crossbook-evil-eval.py`. |
| `datasets/owner-rated-2026-10-15.jsonl` | Owner-rated answer rows used by the ranking and judge checks. |
| `datasets/sealed-forms.json` | Sealed question forms never used for training. |
| `datasets/demo-questions.md` | Demo questions for a first run of the app. |

### Plans

| File | What it is |
| --- | --- |
| `plans/backlog.md` | Open and parked work: figure understanding, conversational clarify, caption quoting, and items that need an owner decision. |
| `plans/companion-track.md` | The live multi-turn companion path and where each piece lives. |
| `plans/conversation-map.md` | Read before touching history or the thread: what may change, what breaks the quote check. |
| `plans/pane-now.md` | What the reader, library and margin do today, with the file for each behavior. |
| `plans/figure-understanding-plan-2026-10-15.md` | Design for answering questions about figures (not built). |

### Tooling

| File | What it is |
| --- | --- |
| `prune.py` | Read-only rot check: stale, unindexed, missing, unreferenced and over-versioned files. |

## History

`../archive/` holds the dated reports, evidence, probes, plans and the original
build plan. Use `git log` and the archive to see how a decision was reached;
`../docs/DECISIONS.md` holds the current reasons.
