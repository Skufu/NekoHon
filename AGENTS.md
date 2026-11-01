# AGENTS.md — ask-this-book

> **Context budget (2026-10-30, measured).** This file is ~8k tokens after the history move; keep it under 12k. Oct 29–30: 2.29B re-read tokens against 4M written; one audit session made 602 calls at a 457k median context, and a fresh session already starts at 72k. Start one session per task, do not resume a session past ~100k context, run a subagent for one question then stop, and never re-ask a question inside the same long chat. Dated history goes to `docs/history-2026.md`, never back into this file. Numbers and the fix list: `~/.agents/handoff/ask-this-book.md`, section "Token budget".

Agent entry point for this repo. Read `GOAL.md` (the goal + constitution, the
stable layer), then this file, then `BUILD_PLAN.md` (the living build plan;
renamed from `README.md` during the `epub-local` repo prep — references below
to "the README" mean it) and the current phase brief in `artifacts/`. The
human-facing front page is `README.md` (overview, quickstart, tests; this file
stays the rules-and-state authority).

## What this is

An offline multi-volume book companion running on an open local stack
(managed via `requirements.txt`). A catalog of books (`data/books.json`:
`fde` Fundamentals of Data Engineering, `quantization` Quantization and Fast
Inference, `ddia` Designing Data-Intensive Applications) is ingested from EPUB
or PDF into storage (JSON or SQLite FTS5 and binary vector files), passages are
retrieved using hybrid search accelerated by `numpy` SIMD vectors and optional
local rerankers, and questions are answered from the retrieved passages in two
modes: `answer` (quote-first answers with `[Ch. N]` citations; the window
default; since the 2026-10-15 alignment it is served the same trained prompt as
`ask`) and `ask` (a checked quote plus a gloss). Cited figures still attach. All
inference is local — in-process or localhost Ollama on `127.0.0.1:11434`. No
cloud APIs.

## Where things live

- `GOAL.md` — goal + constitution (stable). `BUILD_PLAN.md` — living plan.
  `README.md` — human front page. `GLOSSARY.md` — the vocabulary in plain
  words (read it when a term is unclear). `requirements.txt` — Python dependencies
  for the open local stack (SQLite FTS5, `numpy` SIMD vector search, `tokenizers`,
  local rerankers, PDF/EPUB ingestion, in-process or Ollama inference).
- Engine: `server.py` (HTTP + the frozen `POST /ask`),
  `answer.py` (ask/answer modes, the `[Ch. ` retry), `retrieve.py` (index +
  search), `store.py` (SQLite index store + FTS5 tables), `fts_index.py` (FTS5
  scoring and persistence-aware connection), `ingest.py` (EPUB -> index),
  `preprocess.py` (+ `vendor/`, text preprocessing tools), `canonical.py`,
  `prompt.py` (model tags + system prompts), `fusion.py`, `keywords.py`,
  `readings.py`, `captions.py`, `figures.py`, `observe.py` (local per-request
  JSONL trace recorder), `agentic.py` (prototype, not wired).
- Checks: `preflight.py` (readiness), `verify_index.py` (index hygiene),
  `artifacts/harnesses/trace_inspect.py` (CLI inspector for live `artifacts/runs/traces.jsonl`
  and stage-attributed `fair-eval` runs; `--json` for agents),
  `tests/` (`python -m unittest discover -s tests`, including `test_query_understanding.py`, `test_generalization.py`, and `test_observability.py`).
- `artifacts/` — everything dated and measured: `probes/` (scripts that run
  things), `reports/` (the why + verdicts), `evidence/` (raw run outputs),
  `harnesses/` (battery, sweeps, groundedness, judge, secret scan),
  `datasets/` (bench, sealed suite, training lists). Index + rules:
  `artifacts/README.md`; rot check: `python artifacts/prune.py --plan`.
- `artifacts/plans/` — forward-looking plans, one file per track with its
  status (the dated records stay in `artifacts/reports/`). Companion track
  index: `artifacts/plans/companion-track.md`. Conversation map (read before
  touching history/thread): `artifacts/plans/conversation-map.md`. Current pane:
  `artifacts/plans/pane-now.md`.
- `.agents/skills/` — project-local agent skills; `book-companion-ui/` is the
  UI/taste skill — load it for any window, reader, or frontend work.
- `web/` — the Next.js frontend (reader + ask panes; the frontend exception):
  `npm run dev` on :3100 against the engine on :8000. File map, engine calls,
  and conventions: `web/README.md`; condensed design research:
  `.agents/skills/book-companion-ui/references/gloss-and-craft.md`; phase
  record: `artifacts/reports/frontend-phase1-2026-10-15.md`.
- Gitignored, machine-local: `books/`, `data/` (index, finetune data, model
  artifacts), `artifacts/runs/` (server logs, `traces.jsonl` runtime traces, + start scripts).

## Goal vs plan (read `GOAL.md`)

`GOAL.md` holds the goal and the constitution — the only parts that rarely
change. `BUILD_PLAN.md` and the dated reports are tactics that expire. Two
rules follow:

- **Only `GOAL.md` can block work.** A rule in a dated doc never blocks a
  mean; it is a hypothesis, superseded by a new dated note. Lock the goal, not
  the method.
- **Every "stop and say" is a verification gate, not a permission gate.**
  Change the tactic, then re-run the gates (battery, pins, trial probes). Do
  not ask permission to replace a means; do not change one without re-running
  the gates.

**Constitution (short copy of `GOAL.md` — keep in sync):** local only (in-process
or localhost Ollama; zero cloud runtime calls; one eval-only cloud-judge
exception) · open local stack (libraries and binary formats unrestricted; pick by
measured speed, accuracy, footprint) · grounded (quotes come from the book;
repairs never invent text) · refusal is exactly `Not in this book.` · measured,
not asserted (negative controls score zero, unvarnished pass/fail reporting).
Only this list can block work.

## Hard rules (do not break)

- **Local runtime only.** All runtime execution, inference, and retrieval stay
  strictly on this machine: in-process (`llama.cpp`, `onnxruntime`, `torch`,
  `sentence-transformers`, `numpy`, etc.) or localhost (Ollama at
  `127.0.0.1:11434`, engine at `:8000`). Zero cloud runtime calls. One bounded
  exception, evaluation only: eval and judge artifacts may call the configured
  judge — `opencode/deepseek-v4.1-flash-free` with only
  `opencode-go/deepseek-v4.1-flash` as fallback (owner decision 2026-10-29;
  `JUDGE_BACKEND=ollama` explicitly selects offline granite); the key
  comes from the environment or `.judge-key` (gitignored, never committed). The
  engine, server, and batteries never call outside localhost.
- **Frontend local runtime.** The Next.js UI under `web/` stays local-only: the
  built UI makes no external requests (no webfonts, CDNs, telemetry, or
  analytics), and in production the engine serves the built assets so the user
  still opens one local URL.
- **Storage formats & assets.** The book index is one SQLite database per
  book (schema + FTS5 tables + float64 embedding blobs); `<book>.sqlite` is the
  engine's store, and the loader still reads legacy JSON indexes for migration.
  Binary vector storage (`.npy`, float32 blobs, `.npz`), ONNX, and GGUF remain
  first-class formats. Pictures stay as individual files under `data/figures/`.
  Do not base64 images into indexes or databases.
- **Git hygiene.** Never commit large model weights, index binary artifacts, or
  book binaries to the repository. Standard packages and model downloads do not
  require arbitrary megabyte permission gates, but large files must remain
  gitignored under `data/` or `books/`.
- Only the documented routes: `POST /ask`, `GET /health`, `GET /figures/{id}`,
  `GET /` — plus the frontend plan's approved reader additions (2026-10-15):
  `GET /chunks` and `stream=1` on `POST /ask` (NDJSON: token, reset, final,
  error). No other route. `POST /ask` request/response shape is frozen (README
  "Contract"); `mode` is `ask`, `answer`, `explain`, `quiz`, or `import`
  (drag-and-drop EPUB; `server.py` `EXTRA_MODES`). When
  `refused: true`, `answer` is exactly `Not in this book.` — that sentence,
  period included, and nothing else. In `answer` mode the model's first line
  must be that exact sentence for a refusal; in `ask` mode a line that starts
  that way and then keeps talking is not a refusal.
- Phases are a plan, not a contract. If the plan looks wrong, say so — honest
  architect, not a yes-man. Then change it and re-run the gates (battery,
  pins). Reordering or skipping a phase to serve the goal is allowed; you owe
  the repo a re-run and a plan update, not a permission request (see "Goal vs
  plan").
- `rag-template/` is read-only reference. Never touch its `.venv`. Porting code
  from it requires a measured win recorded first, or it does not land.
- Do not commit unless the human asks.
- Reset the engine with the model (user rule 2026-10-14): anytime the answer
  model changes — a new `ANSWER_MODEL` default, an env seam, a new Ollama tag
  — and after any `*.py` edit, restart `artifacts/runs/start-engine.bat`
  before measuring or serving, and check `/api/ps` to confirm the loaded
  model. A running server keeps the code and model it loaded at start
  (measured: a 14:46 server served `smallbook_x2`, uncapped and un-retried,
  through 22:13 while the tree said x2d).
- Improvements must generalize, not fit this book's test set — the system has
  to hold for other books later. No chunk ids, figure ids, chapter numbers,
  query strings, or book ids in the logic modules (`answer.py`, `canonical.py`,
  `captions.py`, `figures.py`, `keywords.py`, `observe.py`, `preprocess.py`,
  `prompt.py`, `readings.py`, `retrieve.py`).
  Pins and ids belong in tests, the battery, and docstrings.
  `tests/test_generalization.py` enforces the literal part.
  `tests/test_query_understanding.py` enforces that query understanding,
  canonicalization, intent classification, passing-mention grounding, and
  coreference resolution remain strictly book-agnostic. Thresholds are the
  subtler half: a constant is fitted if its stated reason is which known test it
  keeps green (e.g. `RARE_DF = 8` justified by "keeps 'capital' out"), not if it
  falls out of a rule that survives a different book. Say so when you see one.
  Do not quietly tune a constant until a battery run passes.
- Report measured results, not impressions: files changed, exact command, real
  output. If a test fails, say so with the actual failure. An improvement that
  cannot be told apart from luck is not measured: report the before number, the
  after number, and what was held constant.
- Diagrams anywhere (chat, docs, artifacts) are **real mermaid diagrams**
  (they render) — never ASCII sketches. User decision 2026-10-13; the model
  example is `artifacts/reports/system-map-2026-10-13.md`.
- State over prose: inspect live code variables or data lines (e.g.
  `len(PERTURB_SWAPS)`) before quoting metrics from markdown reports. Treat
  documentation, ADRs, status files, and READMEs as unverified claims until the
  source code agrees.
- **A plausible example is not evidence.** Before repeating a quote, an example,
  or a failure count, open the source and check it. Owner question 2026-10-24
  ("but in this one is there really an ACID term?") found what the summary had
  not: an old follow-up row attached a rewritten ACID quote to an OLTP passage,
  and 10 of that set's 15 quotes exist nowhere in the books. The engine was
  fine; the data factory was not. A sentence that reads right is not a sentence
  that has been checked.
- **Scope the checker before believing its number.** A first pass reported 88
  unverifiable quotes in the 400 assembled rows. Scoped to in-book chunk ids and
  including figure captions, the count is 0; the misses were other-domain rows
  and captions the check never read. State the scope next to the count. A red
  number from an unscoped checker is a bug in the checker until proven
  otherwise. `tests/test_training_quotes.py` is the mechanical half of this
  rule: every in-book quote in `data/finetune/*.jsonl` must be verbatim.
- Verify disk state first: check `git status` or inspect target directories
  before proposing a build action, to avoid proposing work that has already
  shipped or files already built.
- Mechanism precision: distinguish between true n-gram repetition loops and
  boundary continuation length-stops, as their mitigations operate at
  completely different layers (refusal ratio vs `num_predict`).


## Observability and failure diagnosis

- **Runtime trace log.** `observe.py` records one JSON object per request using `contextvars` across `server.py`, `retrieve.py`, and `answer.py` (including `anomalies`, `selection_preview`, `history_preview`, `lexical_top5`, `pre_rerank_top5`, `answer_preview`, and `citations_detail`). Live HTTP calls (`POST /ask`, `POST /ask` with `stream=1`, and `GET /retrieve`) append to `artifacts/runs/traces.jsonl`. Set `OBSERVE=0` to disable tracing or `OBSERVE_LOG=<path>` to write elsewhere. Unit tests skip default log writes when `unittest` is loaded unless `OBSERVE_LOG` is set. Tracing never alters HTTP routes or response keys.
- **Inspect with `trace_inspect.py` (or `python observe.py`), not ad-hoc scripts.** Do not write throwaway Python scripts that call `retrieve.search` directly to debug bad answers. Raw `retrieve.search` skips canonicalization, typo repair, RRF fusion, phrase boost, and pre-LLM guards, so its ranks do not match `shown_passages` (the exact 5 passages sent to the model). Run `python observe.py --json` (which delegates to `artifacts/harnesses/trace_inspect.py`) instead:
  - Live log (`artifacts/runs/traces.jsonl`): `python observe.py` (summary), `--last 5`, `--failures` (or `--anomalies`), `--slow`, `--book <book_id>`, `--id <trace_id>`, `--diff <id1> <id2>`, `--reconstruct` (rebuilds chunk text and headings from local `data/index*.json` since raw book prose is not duplicated into trace logs).
  - Offline retrieval & guard dry-run (zero LLM calls): `python observe.py --dry-run "<question>" --book <book_id> --json` (alias `--explain-query`, with optional `--mode`, `--pin`, `--select`).
  - Eval runs (`fair-eval.py` JSON): `python observe.py --eval <run.json> --failures`, `--stage <bucket>`, `--id <item_id>`, `--compare <older_run.json>`. Always append `--json` when parsing from an agent.
- **Isolate the failing stage before changing code or training data.** Every `fair-eval.py` item carries `trace` and `diagnostics` attributing failures to one stage:
  1. Pre-LLM guards (`guard_false_refusal` when `query.guard_blocked` fires on an answerable item; `trap_false_answer` when an out-of-book trap slips past both guards and the model).
  2. Retrieval (`retrieval_miss` when no gold chapter or passage appears in `retrieval.shown_passages`).
  3. Generation (`missing_key_fact`, `wrong_citation`, or `false_refusal` when a gold passage is in `shown_passages` and `llm.calls` ran).
  4. Post-LLM transforms (`outcome.transforms`: `parse_refused`, `half_covered_refused`, `citation_aligned`, `retry_uncited`, `list_expanded`) and Ollama runtime health (`llm.ttft_ms`, `llm.tok_per_sec`, `vram_load_ms` >= 100 ms cold-load stalls).
- **Locked split privacy.** `trace_inspect.py` hides questions, answers, and chunk IDs on `locked` split items unless `--allow-locked-text` is passed. Never run `fair-eval.py --split locked` or `--allow-locked-text` during normal iteration; iterate on `--split dev`.


## Artifacts policy (read before writing to artifacts/)

- **Docs are engineering records, and this repo is public-facing.** Write
  measurements, decisions, and evidence — never chat transcripts, informal
  user quotes, or session chatter. Attribute a decision as "owner decision
  YYYY-MM-DD", not as a quoted message.
- Runs write to `artifacts/runs/` (gitignored). Promote a run into
  `artifacts/` only when a doc or commit names it, and add its row to the
  index (`artifacts/README.md`) — the index is the gate.
- Zones (migration landed 2026-10-14; only `prune.py` + `README.md` stay at
  `artifacts/` top level — never add new flat files): `harnesses/`
  (reusable runners), `probes/` (dated one-offs), `datasets/` (eval sets,
  question lists), `reports/` (dated .md findings),
  `evidence/<family>/` (dated outputs, one live twin), `runs/` + `scratch/`
  (gitignored scratch). Full table + path snippet: `artifacts/README.md`.
  History bullets below cite pre-migration flat names; resolve them through
  the index.
- **Every artifact type has a home; ask the decision list.** It answers
  "where does this new file go?" in order, including images/screenshots
  (`probes/<capture>-YYYY-MM-DD/` for a one-off series, `evidence/<family>/`
  once a doc names it), notebooks and HTML reports (`reports/`), HTML
  fixtures (`validate/`), and error/stdout logs (`evidence/<family>/` when
  named, otherwise `runs/`/`scratch/`). Nothing lands at the repo root.
- New docs and benchmark outputs carry their date in the name:
  `family-YYYY-MM-DD[-label].ext`.
- One live twin per family: the latest run plus any run a doc names;
  superseding a run means deleting the old one in the same commit that
  supersedes it (numbers folded into the doc first).
- **Staleness gate:** a benchmark or doc dated two or more days ago is
  stale. Do not trust its numbers, do not build on it, do not tune code to
  match it. Re-run it, or ask the user first.
- Prune before docs commits: `python artifacts/prune.py --plan`.

## Current state (summary — history lives in `docs/history-2026.md`)

Default answer model `nekohon_q35_2b_x3_2e` (Qwen3.5-2B, Q4_K_M, 1.31 GB).
Five books in `data/books.json`: `fde`, `quantization`, `ddia`,
`ai-engineering`, and one imported agents volume. Engine `:8000`, web `:3100`.
Append new dated results to `docs/history-2026.md`; this block stays a summary.

**Known open defects (2026-11-01)**
- Judge calibration v3: 21 of 22 known cases; fixture `r3-9011ed66` flips
  2 accept / 1 reject, so content grading is blocked.
- `fusion.fuse()` still computes an RRF score and returns only the hits
  (`fusion.py:183`), so a fused reorder is invisible in the trace the way the
  phrase boost used to be; the phrase boost now records `phrase_score`.

**Recently landed**
- A "what is X" question whose phrase the book never writes now refuses
  (2026-11-01): `has_uncovered_subject` catches the 2-3 word subjects the
  word-level vocabulary guard cannot, after the QA pass found `what is data
  engineering` answered with an invented definition in a book with 0 of 473
  chunks containing the phrase.
- The citation is a gate, not a meter (owner decision 2026-11-01): an answer
  body that names no passage is recovered with its citation when the shown
  passages really contain the sentence (`citation_recovered`), and is otherwise
  the exact refusal (`uncited_refused`). Retires the old "a refusal is never
  fabricated from a failed check" policy and its two tests.
- Follow-up retrieval drift fixed (2026-11-01): the reader's pin leads the
  window instead of replacing it, and the history-turn sequence window narrowed
  from 4 chunks to 2. Gold-chunk loss on 15 follow-ups went 11 of 15 -> 0 of 15
  with a pin and 2 of 15 -> 0 of 15 without one; trace regression 12/12,
  hard-mt 12/12, fair dev 44/60 unchanged.
- Index storage is SQLite FTS5 (2026-10-31): one `data/index[.<book>].sqlite` per
  book, `store.py` owns schema + atomic writes, persisted FTS tables replace the
  per-process build, and the JSON indexes were migrated and removed.
- Comparison answers: 9/20 -> 20/20 on its matrix (2026-10-29).
- Examples follow-up and plain-register routing fixes behind trace `248e2fb886c4`.
- Reading progress no longer counts shelf scroll; the reader restores its passage.

**Where the detail lives**
- Dated history: `docs/history-2026.md`.
- Measurements and verdicts: `artifacts/reports/`, indexed in `artifacts/README.md`.
- Eval-track state and next step: `~/.agents/handoff/ask-this-book.md`.

## Verify

- `python -m unittest discover -s tests` (must stay green)
- Comparison regression: `python -m unittest tests.test_comparison_regression`;
  live matrix: `python artifacts/harnesses/comparison-matrix.py --label after`
  (in-process, no server).
- Setup readiness: `python preflight.py` (read-only; Python version, book,
  index, Ollama, models, vector audit; exit 0 when ready to serve)
- Index hygiene: `python verify_index.py` (read-only; exits 1 on dirty vectors or
  damaged storage) and `python store.py --check data/index.sqlite ...`
  (SQLite quick_check, schema version, FTS row counts)
- Server: `python server.py` -> `GET http://127.0.0.1:8000/health`. A server
  serves the code and model it loaded at start — restart
  `artifacts/runs/start-engine.bat` after any `*.py` or `ANSWER_MODEL` change,
  and check `/api/ps` to see which model is actually loaded (a 14:46 server
  kept serving `smallbook_x2` with no cap/retry until restarted 22:26,
  measured 2026-10-14). Reader routes live-checked 2026-10-15: `GET /chunks`
  (reader payload) and `stream=1` on `POST /ask` (NDJSON token/reset/final/error).
- Bake-off: `ANSWER_MODEL=<tag> python server.py`, then `python artifacts/harnesses/step2-battery.py`. Default is `nekohon_q35_2b_x3_2e` (adopted 2026-10-24; revert with `ANSWER_MODEL=nekohon_q35_2b` or `=nekohon_x3`, or `=nekohon_x3_mobile`, `=smallbook_x3_mobile`, `=qwen2.5:7b` — tags verified against `ollama list` on 2026-10-25); keep exactly one listener on :8000.
- Answer mode: `BATTERY_MODE=answer python artifacts/harnesses/step2-battery.py`; sweeps `SWEEP_MODE=answer python artifacts/harnesses/qa-sweep.py <label>`; groundedness `python artifacts/harnesses/groundedness.py --battery --label <name>` or `--label <name>` over `datasets/qa-questions-overnight.json` (in-process, no server needed).
- Definitional (acronym/short) questions: `python artifacts/harnesses/fair-eval.py --dataset artifacts/datasets/definitional-2026-11-01.jsonl --split dev` — 10 items, baseline 9/10. Follow-up retrieval drift: `python artifacts/probes/probe-followup-drift-2026-10-29.py` (no LLM; prints gold chunks lost with and without the reader's pin).
- Sealed hold-out: `python artifacts/harnesses/sealed-eval.py [model]` (30 items, in-process, no server); leakage audit `python artifacts/probes/leakage-audit-2026-10-24.py`; unit tests `python -m unittest tests.test_eval_leakage tests.test_harness_fairness`. Fairness rule and re-pins: `harnesses/fair_cite.py`, `datasets/battery-pins.json`.
- Agentic prototype (not wired): `python artifacts/probes/probe-agentic.py` (live Ollama, 5 asks).
- Plain register: `python -m unittest tests.test_plain_register`; scorecard draws (cloud judge) `JUDGE_BACKEND=cli python artifacts/harnesses/eval-plain.py --variants wired --label wired` (replay with a new label); judge flip probe `python artifacts/harnesses/judge-stability.py --file evidence/eval-plain/eval-plain-v6-openai-muse-spark-1-3-contributor.json --match <question substring> --n 3`; live route check: `answer` mode with "explain data engineering in simple words".
- Canonicalization & Query Understanding: `python -m unittest tests.test_canonical tests.test_query_understanding`; live check:
  a bare phrase in answer mode ("watermark") answers in question form and the
  answer ends with `Asked as: "What is watermark?"`; mutation check
  `python artifacts/probes/probe-test-mutations-2026-10-13.py` (5 breaks, 0 survivors).
- Judge backends: default `cli:opencode/deepseek-v4.1-flash-free` since 2026-10-29, only `opencode-go/deepseek-v4.1-flash` as fallback; actual model is in each call's `LAST_CALL`. Explicit offline selection is `JUDGE_BACKEND=ollama` (`granite4.1:8b`). Judge-only replay from a saved run: `python artifacts/harnesses/eval.py --judge-only --label v1`; calibration across judges: `python artifacts/harnesses/judge-agreement.py eval-v1-ollama-granite4-1-8b eval-v1-openai-muse-spark-1-3-contributor`. The engine never uses the key.
- Secret scan: `python artifacts/harnesses/secret-scan.py` (git history + tracked tree; masked output; exit 1 on any hit). Clean 2026-10-13: this repo 516 blobs, 0 hits; `rag-template` 170 blobs, 0 hits.
- Artifacts: index + rules `artifacts/README.md`; prune planner `python artifacts/prune.py --plan`.

## Machine facts (this Windows box)

- Use system `python` (3.12.5). The README's `env -u PYTHONPATH` wrapper is a
  macOS note; ignore it on Windows.
- Ollama: `C:\Users\ADRIAN\AppData\Local\Programs\Ollama\ollama.exe`, v0.40.3.
  Upgraded 2026-10-11 from v0.4.3. Installer was `OllamaSetup.exe`, 1578217944
  bytes, signed by Ollama Inc., silent install exit 0. Not on PATH. Start it
  with the full path + ` serve`. `ollama --version` with the server up prints
  `ollama version is 0.40.3`.
- On disk: `nomic-embed-text:latest` (274 MB, pulled 2026-10-11). Smoke embed
  returned 768 dims. `nekohon_q35_2b_x3_2e:latest` (1.3 GB, digest `cba00d4abf1f`,
  2026-10-24) is the desktop default; `nekohon_q35_2b:latest` (digest
  `f17a0478a7d1`, 417-row run), `nekohon_q35_2b_x3:latest` (digest
  `384625ef9b27`, 3-epoch run) and `nekohon_q35_2b_r3:latest` (digest
  `6ce39fe92a71`, 1,121-row round 3, not adopted) stay as candidates;
  `nekohon_q35_2b_r4_1e:latest` (round 4, history rows, not adopted) also stays
  on disk; `nekohon_x3:latest` (1.93 GB,
  digest `5a9525f8d0ac`) is the previous default and the revert; `qwen3.5:2b-q4_K_M`
  and `qwen3.5:4b-q4_K_M` stay as zero-shot baselines. `nekohon_x3:latest` (1.93 GB (1,840.5 MiB), digest `5a9525f8d0ac`) is the finetuned
  answerer and app default since 2026-10-17 (renamed from `smallbook_x3:latest`, digest `4d755a3b108d`,
  which stays registered as an alias); `nekohon_x3_mobile:latest` (986 MB (940.4 MiB), digest `89e6798ed288`;
  renamed from `smallbook_x3_mobile:latest`, digest `d3508a8ff376`, kept as an alias)
  is the companion mobile student; `nekohon_q35_2b:latest` and `nekohon_q35_2b_x3` (1.3 GB each;
  the first Qwen3.5 run and the 844-row 3-epoch run), `nekohon_q35_2b_r3` and `nekohon_q35_2b_r4_1e`
  (not adopted), and `nekohon_q35_2b_r5` (870 rows, 2026-10-25, not adopted) also stay on
  disk; `qwen2.5:7b` (4.7 GB, Q4_K_M, since 2026-10-11) is the original
  teacher and the fallback answerer — newer students distill from the
  **Qwen3.8-27B** captures, which run on Colab, not on this box (kit:
  `artifacts/reports/teacher-capture-colab-2026-10-15.ipynb`). Naming trap
  (2026-10-23): never call the 7B "the teacher" without "original", and never
  use it to author evaluation questions. Eval and bench questions are
  hand-written by the agent from the passages (see
  `artifacts/datasets/wide-net-2026-10-23.jsonl`); a 7B writes them in the
  passage's own words, which tests copying, not retrieval. Bake-off pulls 2026-10-12 (9,945 MB approved):
  `qwen3:4b-instruct` (2,497 MB), `granite4.1:3b` (2,100 MB), `granite4.1:8b`
  (5,348 MB).
- MLX runtime installed 2026-10-11 from `ollama-windows-amd64-mlx.zip`,
  1403168802 bytes, extracted into the Ollama program folder. Zip deleted.
  `embeddinggemma-2:270m-bf16-text` (574 MB) is on disk. Smoke embed returned
  768 dims. Runner shows `mlx`, `100% GPU`. Do not pull `embeddinggemma` (v1)
  or the picture/audio tags. This book only needs the text tag.
- `agent-browser` (browser-automation skill) does not start on this box as of
  2026-10-12: its daemon fails to bind a TCP socket (os error 10013, Windows
  excluded port ranges). Use a real browser for window checks.
- Do not delete `tests/__init__.py`: a user-site `tests` package shadows the
  directory without it (the file itself explains why).
- `books/` and `data/` are gitignored. On a fresh machine, re-run Phase 0: the
  original EPUB path is recorded in `books/SOURCE.txt`.
- Multi-Book Library & Catalog landed 2026-10-17 (`data/books.json`):
  * `fde`: *Fundamentals of Data Engineering* — 1,042 chunks · 111 figures · 17 chapters
  * `quantization`: *Quantization and Fast Inference* — 473 chunks · 76 figures · 7 chapters
  * `ddia`: *Designing Data-Intensive Applications* — 1,306 chunks · 90 figures · 17 chapters
  * Total catalog corpus: **2,821 passages** and **277 figures** across **41 chapters**.
  * Manning EPUB `div.figure-container` and dot-number normalization (`Figure 1.1` -> `figure-1-1`) supported in `ingest.py`.
  * Heading-based non-teaching filter removes 151 alphabetical index chunks in `ddia`.
  * Filesystem-driven figure resolution in `figures.py` (zero hardcoded book IDs).
  * Web drag-and-drop `.epub` ingestion via `POST /ask` mode `"import"` (`importEpubBook`).
- R15 Caching & Retrieval Speedups measured 2026-10-17:
  * `_POSTINGS_CACHE`: `82.38 ms -> 0.0018 ms` (45,000x faster).
  * Pre-normalized unit-vector dot product (`_uvec`): `51.69 ms -> 19.75 ms` (2.6x faster dense ranking).
  * `_SORTED_WMAP_CACHE`: `19.86 ms -> 5.71 ms`.
  * `INDEX_CACHE` + `CHUNKS_GZIP_CACHE`: `1.14 MB -> 328 KB` over HTTP (71.7% network reduction).
  * `keep_alive: "24h"` zero cold-start model pinning in Ollama.
  * CSS `content-visibility: auto; contain-intrinsic-size: auto 320px;`: 99.5% reduction in active layout DOM nodes for 1,300+ chunk volumes.
- Multi-turn adversarial evaluations & quality gates:
  * `harnesses/adrian-eval.py`: 35 real-world multi-turn conversational scenarios across 97 turns (32/35 passed, 91.4%).
  * `harnesses/crossbook-evil-eval.py`: 30 cross-book multi-turn scenarios across 66 requests over `fde`, `quantization`, and `ddia` (24/30 baseline, 26/30 current fair run).
  * `datasets/followup-evil-train-2026-10-17.jsonl`: 100 adversarial follow-ups.
  * 460 unit tests across 39 test modules (`python -m unittest discover -s tests`) as of 2026-10-25: 458 pass, 2 pre-existing failures in `tests/test_frontend_rules.py` (raw colour/shadow in the uncommitted `web/` work).
  * `harnesses/hard-mt-eval.py`: 12-item hard multi-turn bench (elision, pronoun, distraction, fabricated attribution), frozen sha256; default `nekohon_q35_2b_x3_2e` 12/12 after the 2026-10-25 engine fixes, sealed 27/30, hard bench 59/60, adrian 32/35.

## Post-v1 backlog (not approved; confirm before starting)

- Caption quoting: README Figure honesty allows quoting the caption; the
  pipeline currently feeds only passages.
- `keep_alive` in the Ollama requests: removes the ~25 s cold-load; warm asks
  are ~1 s (measured). Cost: ~5 GB VRAM held.
- Figure understanding (direction recorded 2026-10-15, not approved): ask
  about a figure ("explain figure 4.4") and get the figure shown, the book's
  words about it, and a reading of what it depicts. The plan — and the verdict
  on the "move the runtime to a VL model" idea (vision belongs at ingest, not
  at inference) — is `artifacts/plans/figure-understanding-plan-2026-10-15.md`;
  Phase 0 is figure-number normalization ("4.4" -> "4-4"), independent and
  cheap.
- LFM3-1.7B as an answer-model base (candidate 2026-10-30, not approved, owner
  direction: revisit after the training dataset is repaired). Liquid's
  tri-hybrid 1.73B, 256K context, Q4_K_M 1.10 GB, LFM Open License v1.0
  (commercial use under $10M revenue; redistribution must carry the license and
  a modification notice). Fine-tunes through TRL SFT + LoRA with LFM3's own
  target modules (`w1/w2/w3`, `in_proj/out_proj`, `q/k/v/o_proj`, optional
  `gate_proj`) and `enable_thinking=False`; LEAP is LFM2-only and there are no
  Unsloth LFM3 repos. Runtime floor is Ollama >= 0.40.12 (Apple silicon) /
  0.40.13 (Linux, Windows) — this Mac is on 0.40.2 and the Windows box on
  0.40.3, so an upgrade precedes any test. Facts, gates, and the cheap
  pre-training probe: `artifacts/plans/lfm3-base-candidate-2026-10-30.md`.
  Owner order 2026-10-30: repaired-data retrain first, then stock LFM3, then
  LFM3 SFT on the same repaired corpus — one factor per arm.
- Teacher upgrade (proposed 2026-10-30, not started, owner direction: a Colab
  GPU session is available, so do not limit the teacher to Qwen3.8-27B).
  Measured 2026-10-30: the account allocates **A100-SXM4-40GB** (40,960 MiB
  VRAM, 83 GB host RAM), not an 80 GB card — "High-RAM" is host memory, and
  `H100` is ineligible, so the teacher runs at Q4-Q6, not Q8.
  The teacher's only job is quote-verbatim + gloss + exact refusal, so public
  agentic benchmarks are not selection evidence. Arms that fit: incumbent
  Qwen3.8-27B (UD-Q4_K_XL 17.6 GB) plus a UD-Q6_K (22.0 GB) quant control, and
  three challengers — Nanbeige4.3-33B (Q5_K_M 24.7 GB; its Q6/Q8 do not fit),
  Gemma-4-31B-it (Q6_K 25.2 GB), Muse-Glimmer-30B (UD-Q6_K_XL 26.3 GB).
  Selection runs on the capture notebook's existing behavioral pre-gate with
  the promotion rule fixed in advance. Excluded: DeepSeek-V4.1-Flash-1017
  (~160 GB IQ2 shards, and the judge family), flint (agentic coding), and the
  Saluki/Swift/GSQ-RCO 27B builds, which are quantizations of the incumbent
  rather than upgrades. Plan: `artifacts/plans/teacher-upgrade-2026-10-30.md`.
- Conversational companion (direction recorded 2026-10-15, not approved):
  the user wants the companion to eventually hold a conversation, so
  degenerate input (bare fragments like `how do`) becomes a *conversational*
  turn (a clarifying question or follow-up) instead of the binary
  answer-or-refuse. Parked; not this build. If taken up it needs a third
  response type (clarify), conversation state and a new/extended API contract
  (`POST /ask` is frozen), multi-turn training and eval data, and a re-think
  of the sealed suite's fragment class (which currently requires fragments
  ANSWERED). Until then the refusal sentence keeps one meaning: the book does
  not cover the thing — never "I did not understand you" (rule recorded
  2026-10-15 with this direction).
