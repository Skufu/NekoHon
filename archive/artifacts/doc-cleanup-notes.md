# Doc cleanup notes (2026-10-15)

Allowed edits only: `README.md`, `SETUP-MACOS.md`, this file.
No forbidden sources were opened (GOAL.md, AGENTS.md, BUILD_PLAN.md,
GLOSSARY.md, .cursorrules, .judge-key, books/, data/, vendor/, any .py,
web/ source beyond `web/README.md`, window/).

Verification used: tree listing, `find_path`, `artifacts/reports/*` and
`artifacts/evidence/*` existence, `web/README.md`,
`artifacts/reports/frontend-phase1-2026-10-15.md`,
`artifacts/reports/x2e-verdict-2026-10-15.md`,
`artifacts/reports/x2d-plan-2026-10-14.md`,
`artifacts/reports/retry-safety-net-2026-10-14.md`,
`python -m unittest discover -s tests` → **Ran 246 tests … OK**,
`git remote -v` (nekolabs → nekolabs-studio/epub-local; origin → Skufu/ask-this-book).

---

## Edits made

### SETUP-MACOS.md — answer model name (stale vs README + artefacts)

| Old claim | New claim | Proof |
| --- | --- | --- |
| Answerer is `smallbook_x2` (intro, RAM note, Ollama step, Docker) | Answerer is `smallbook_x2d` | README Models table + Limits; `artifacts/reports/x2e-verdict-2026-10-15.md` ("x2d stays the default"); `artifacts/evidence/x2d-session-2026-10-14/` present |
| Import: `ollama create smallbook_x2` | Import: `ollama create smallbook_x2d` | same; x2d session + x2d-plan import record |
| Recipe pointed only at `smallbook_x2-rebuild-2026-10-14.md` | Points at x2d session / x2d-plan / x2e-verdict; keeps x2 rebuild as earlier lineage | tree has those paths; no `smallbook_x2d-rebuild-*.md` exists |
| Teacher described as rebuild/revert only | Teacher is also the fresh-clone fallback (`ANSWER_MODEL=qwen2.5:7b`) | matches README Quickstart (already correct there) |
| Step 5: bare `python3 server.py` only | Documents `ANSWER_MODEL=qwen2.5:7b` fallback and points at `web/README.md` for the Next reader | `web/README.md` + README Quickstart |

### README.md — test count (measured)

| Old claim | New claim | Proof |
| --- | --- | --- |
| Status: "223 unit tests green" | "246 unit tests green"; status date → 2026-10-15 | `python -m unittest discover -s tests` → `Ran 246 tests in 1.297s` / `OK` |
| Testing §1: "223 tests, green (0.6 s on this box)" | "246 tests, green (1.3 s on this box)"; added reader routes | same run |
| Repo layout: `tests/ 223 unit tests` | `tests/ 246 unit tests` | same |
| Ledger rows "210 tests" / "223 tests" (2026-10-13 / 2026-10-14) | **left alone** | dated historical ledger entries |

### README.md — default model / sealed suite / x2e (artefact-proven)

| Old claim | New claim | Proof |
| --- | --- | --- |
| Limits: sealed suite bare 41/50, order 20/40; 7B 140/160 under retry; "Next build in flight" for 27B student | Post prompt-alignment (2026-10-15) x2d **160/160**, 7B 160/160; x2e built and **not adopted**; pre-fix numbers remain cited via retry-safety-net | `artifacts/reports/x2e-verdict-2026-10-15.md` |
| Roadmap finetune: only x2c not-adopted note | Adds x2e not-adopted; x2d remains default | same verdict |
| Status block silent on x2e / frontend phase 1 | Mentions x2e not adopted + engine half of frontend phase 1 | x2e-verdict + frontend-phase1 report |

### README.md — HTTP / UI stale vs landed frontend

| Old claim | New claim | Proof |
| --- | --- | --- |
| HTTP table: POST /ask, GET /health, GET /figures/{id}, GET / only | Adds `GET /chunks`; notes optional `stream: 1` NDJSON on `/ask`; GET / still serves `window/index.html` (production `web/out` "when wired") | `artifacts/reports/frontend-phase1-2026-10-15.md`; `web/README.md` |
| "Using the window" = only `window/index.html` | Two UIs: v1 window + `web/` Next reader; points at `web/README.md` | `web/` tree (package.json, components, out/); web/README; frontend-phase1 |
| Roadmap: "Frontend (direction 2026-10-13, not approved)" | Frontend phase 1 engine half landed; `web/` is the reader | same |
| Repo layout: no `web/` | Adds `web/` line | tree |
| Doc map: only frontend-navigation-plan "not approved" | Adds web/README, frontend-build-plan, frontend-phase1, x2e-verdict | tree |

---

## Claims left alone (unverified or intentionally historical)

### Cannot verify without forbidden files / runtime we did not re-measure

- Chunk/figure counts **1042 + 111 = 1153** vectors, index ~10.5 MB / 10,528,929 bytes, full re-embed **14.5 s** — cited widely; embedding-audit evidence file exists but its body was not fully re-parsed here; `data/` is forbidden. Left as written.
- Ollama version floor **v0.40.3+** (README Quickstart) — no local version check run in this pass.
- Latency bands (warm 0.4–1.2 s, cold ~25 s, x2d ~0.5–2 s) — historical measured notes; not re-timed.
- Demo expectation "Figure 8-8" for watermark in ask mode — needs live server + book; not re-run.
- Exact battery/sweep/groundedness/eval ledger numbers (every dated table row) — evidence paths exist on disk for the ones checked (`step2-battery`, `phase7-offline`, `eval-v1`, `embedding-audit`, `groundedness`, `qa-sweep`, probe-* dirs); individual numeric cells were not re-diffed against JSON. Treated as historical ledger; left intact.
- Commit hashes in the ledger (`f48910e`, `954860b`) — not re-verified with `git show`.
- "Phases 0-7 pass" / "v1 complete" — would need BUILD_PLAN/AGENTS; left.
- France canary exact refusal text and dense top-20% band story — engine behavior; .py forbidden.
- `anchor` empty for every chunk; digits-not-tokens limit — index/engine; left.
- Agentic prototype "3.1 s total, no measured win" — left (agentic.py forbidden; report may exist but claim left).
- Plain-register night scores (6,7,8 → 9,8) — report path exists; numbers not re-checked.
- ISBN / book bibliographic facts — left (book is local; content not re-validated beyond SOURCE.txt header visible via shell).
- Judge default `muse-spark-1.3-contributor` + OpenCode Go relay env flags — harness paths exist; live cloud call not made. `.judge-key` forbidden.
- `granite4.1:8b` 5.3 GB local judge size — not re-measured on disk.
- Embedder bake-off 10/10 vs EmbeddingGemma 9/10 — BUILD_PLAN-linked historical; left.
- "no pip installs" / "stdlib only" for the engine — no pyproject/requirements in tree (confirmed by find_path); claim stands. `web/` is the documented npm exception.

### Present and consistent — no churn

- Repo short name `nekolabs-studio/epub-local` / internal `ask-this-book` — remotes match.
- Clone URL in SETUP (`git@github.com:nekolabs-studio/epub-local.git`) — matches nekolabs remote host/path (SSH vs HTTPS form left as author wrote).
- Script names: `ingest.py`, `retrieve.py`, `preflight.py`, `server.py`, `verify_index.py`, harness paths under `artifacts/harnesses/` — all exist.
- `tests/fixtures/questions.json` exists.
- `window/index.html` exists.
- `LICENSE` + `vendor/snowballstemmer/COPYING` + `vendor/stopwords-en.txt` exist.
- `books/` is gitignored; local tree still has `fde.epub`, `quantbook.epub`, `SOURCE.txt` (not committed claim is about git policy, not disk).
- Linked reports that were spot-checked for existence all resolve (how-it-works, second-book, retry-safety-net, x2-trial, x2d-plan, smallbook_x2-*, plain-register, query-canonicalization, answer-model-bakeoff-results, mad-phrasing-probe, teacher-capture notebook, coach-review-response, demo-questions, training-list, frontend plans).
- SETUP unit command `python3 -m unittest discover -s tests` and preflight/ingest/retrieve order — matches tree; no contradiction with README once model name fixed.
- Port hygiene note (`lsof` on Mac / `findstr` on Windows) — OS-appropriate; left.
- "Why not Docker" rationale — left (opinion + Metal fact; not contradicted).
- Weak-machine fallback `ANSWER_MODEL=llama3.2:3b` — left (documented non-default).

### Known tension recorded, not rewritten further

- README Offline-proof block still narrates the 2026-10-12 wifi-off run and names `smallbook_x2d` as default since 2026-10-14 — consistent with Limits after this cleanup; left (dated proof section).
- x2d-plan's own mid-file line "smallbook_x2 remains the default (decision pending)" is a pre-retry snapshot inside that report; the later README/x2e-verdict adoption story supersedes it for human docs. SETUP no longer cites x2 as current default.
- Production serving of `web/out` from `server.py` is described in `web/README.md` as "**not wired yet**"; README now says the same. Not claimed as live.

---

## What was not done

- No commits, no sub-agents, no marketing copy, no new product-goal sections.
- No edits to forbidden paths.
- No rewording of accurate prose for style.
- Unit suite was run once to measure count; no harness batteries or Ollama calls.
