# Todo: Deslop the codebase

Every task: worker (worktree, `/agent-skills:build`) → verifier
(`verify` skill + `/agent-skills:review`) → merge → push. "Gate" below means
`verify` offline + cassette replay; "live gate" adds the restarted server and
both batteries.

## Phase 0: Safety net (sequential)

- [x] **T1 Test isolation.** `test_server_multibook` and `test_import_mode_epub`
  build tiny fixture books in a tempdir (patch `server.ROOT`/`INDEX`), never
  touching real `data/`, `books/`, `data/books.json`. Route/packaging tests
  patch `server.get_book_index` with their fake index. Update the 2 highlight
  golden rows whose chapter label changed (`app01` → current ingest label) to
  match the current index.
  - Accept: `python3 -m unittest discover -s tests` → OK; `data/books.json`
    byte-identical before/after a suite run; no assertion weakened.
  - Files: `tests/test_server_multibook.py`, `tests/test_reader_routes.py`,
    `tests/test_server_packaging.py`, `artifacts/datasets/highlight-*.jsonl`.
- [x] **T2 Verify skill + cassette.** Create `.agents/skills/verify/SKILL.md`
  and `cassette.py` (`record` / `replay`). Record on the current tree: battery
  questions + France, modes `ask`/`answer`/`explain`, seeded `quiz`, two
  history follow-ups, one `stream=1` request; fakes keep `_is_live = True`.
  Cassette in `data/verify/` (gitignored). Skill steps: offline gate, cassette
  replay, optional `--live` (restart `server.py` by PID check, both batteries),
  optional Chrome smoke, `git status` check. Also record baseline timings
  (20 in-process asks) to `data/verify/timing-before.json`.
  - Accept: `record` then `replay` on the same tree → identical; a deliberate
    one-character change in a prompt string makes replay fail (then reverted).
  - Files: `.agents/skills/verify/*`.

### Checkpoint 0
- [x] Suite OK (403), cassette 67 cases identical, ask battery PASS (golden 8/10, bar 8), answer battery PASS (10/10); pushed.

## Phase 1: History (parallel with Phases 2–3)

- [x] **A1 Archive history.** `git mv` to `archive/`: `artifacts/reports`,
  `artifacts/evidence`, `artifacts/probes` (except probes the live docs name as
  verification: `probe-highlight-2026-10-16.py`, `probe-test-mutations-*` —
  move those to `artifacts/harnesses/`), `artifacts/validate`, loose top-level
  `artifacts/*.md` and `qa-sweep-questions.json`, `artifacts/plans/*` except
  `companion-track`, `conversation-map`, `pane-now`, `figure-understanding-plan`.
  Archive `BUILD_PLAN.md` only in D1 (not here). `SETUP-MACOS.md` is already removed.
  Update `prune.py` to ignore `archive/`. Harness output paths that pointed into
  `evidence/` write to `artifacts/runs/` (gitignored) instead.
  - Accept: suite OK; every kept harness `--help` runs; `prune.py --plan` runs.
- [x] **A2 Archive agentic.** `git mv agentic.py tests/test_agentic.py archive/`.
  - Accept: suite OK; `grep -r "import agentic"` outside archive → 0.

## Phase 2: Engine (sequential)

- [x] **E0 Group files by role (owner direction 2026-10-23).** Move the 13
  engine modules from the repo root into a package, with `git mv` and
  absolute imports:
  ```
  engine/__init__.py, server.py, ingest.py, figures.py
  engine/retrieval/  retrieve.py fusion.py keywords.py captions.py readings.py preprocess.py
  engine/answering/  answer.py prompt.py canonical.py intent.py
  scripts/           launch.py setup_models.py measure_warmup.py + preflight.py verify_index.py
  ```
  Every `ROOT`/`Path(__file__)` that means the repo root still resolves to the
  repo root (data/, books/, vendor/, window/, web/out). Entry points become
  `python3 -m engine.server`, `python3 -m engine.ingest`,
  `python3 -m engine.retrieval.retrieve`, `python3 scripts/preflight.py`,
  `python3 scripts/verify_index.py`. Update every importer: lazy imports inside
  functions, tests (`import x`, `mock.patch("x.y")`), kept harnesses,
  `scripts/launch.py` (start command + the server-process match, which must
  accept both `server.py` and `engine.server`), the verify skill and
  `cassette.py`, `test_generalization`/`test_query_understanding` file lists.
  - Accept: gate (cassette identical — figure paths and data paths unchanged);
    `python3 -m engine.server` serves `/health`; no `*.py` engine module left at
    the root; `grep -rn "^import answer\|^from answer"` etc. outside archive → 0.

- [x] **E1 Dead code.** Delete `check_quote`, `_maybe_enrich_contextual_gloss`,
  `ingest._marked`, `retrieve.search_with_ranks`, `retrieve.warm_caches`, the
  24 unused regex/set constants in `answer.py`; replace inline copies of
  existing constants (e.g. the `[Ch.` tag regex, 11×) with the constant.
  - Accept: gate; 0 zero-caller functions in engine (grep proof in commit msg).
- [x] **E2 One Ollama client.** New `llm.py`: `generate`, `generate_stream`
  (shared payload builder), used by `answer.py` (re-exported as
  `ollama_generate*`), `server._do_warmup`; `_is_live` kept on the functions.
  - Accept: gate; `server._do_warmup` < 50 lines.
- [x] **E3 Per-request work.** `load_index` builds `chunk_by_id` and
  `chunks_by_chapter` once; replace the ~30 linear scans; one
  `prior_turn_chunk()` replaces the 3 copies; `clean_history` and the
  topic-shift check computed once per request; drop the double LRU on `stem`.
  - Accept: gate; timing replay vs `timing-before.json` not slower (report numbers).
- [x] **E4 Split `answer.py` (1/2).** Move to `sanitize.py`, `quotecheck.py`,
  `listshape.py`, `comparison.py`; message builders into `prompt.py`.
- [x] **E5 Split `answer.py` (2/2).** Move to `conversation.py`, `gloss.py`,
  `context.py`, `explain.py`, `quiz.py`, `freeanswer.py`.
  - Accept (E4, E5): gate; `answer.py` re-exports moved names used by tests and
    kept harnesses; `test_generalization` guards cover every new module.
- [x] **E6 Merge `ask`/`respond`.** One shared pipeline with mode-specific
  generate/parse steps.
  - Accept: gate; neither function > 120 lines.
- [x] **E7 Hotspots.** `intent.compute_dynamic_followups` into slot builders;
  `retrieval_context` into steps; `_resolve_contextual_query` early returns;
  `parse_completion` split; `server.Handler` route bodies into functions;
  remove the `respond.__name__ != "fake_respond"` test hook from production
  code (tests patch differently).
  - Accept: gate; no engine function > 120 lines (AST check in commit msg).
- [ ] **E8 Strip engine comments.** First copy every measured reason (dated
  docstrings, constant reasons, negative results) into `docs/DECISIONS.md`;
  then remove all `#` comments and docstrings from root `*.py`, `scripts/`,
  `tests/`, kept `artifacts/harnesses/`. Keep the shebang and nothing else.
  - Accept: gate; AST/tokenize scan finds 0 comments/docstrings in scope.

### Checkpoint E
- [ ] Live gate PASS; review subagent on the whole engine diff; push.

## Phase 3: Frontend (parallel with Phase 2)

- [x] **F1 Dead code.** Remove the 15 store mirror fields + `syncActiveTurn`
  mirror writes, `getCachedChunks`, needless `export`s, stale
  `next.config.ts` comment. Keep `thread`. Keep `saveHighlights`' legacy key only
  if it is still read for migration (check), else remove.
- [x] **F2 Dead CSS.** Remove the 26 dead classes / 39 rule blocks and 40
  unused tokens; grep template strings before each deletion.
- [x] **F3 Performance.** Margin `compute` / ResizeObserver no longer re-run per
  streaming frame (depend on gloss ids + chunk ids, read glosses via ref);
  elapsed ticker stops rebuilding `glosses`; memoize `getBookStats`; scroll
  progress throttled to change-only store writes.
- [x] **F4 Split `store.ts`.** `lib/persist.ts`, `lib/stream.ts`, one
  `patchTurn` helper for the 19 nested updates. Keys/shapes frozen; update the
  rule test's path only if a pinned string moves.
- [x] **F5 MarginCard.** One `startResize(edge)` + shared move/up handlers for
  the 12 pointer handlers; extract `TurnView`, `FollowUpForm`.
- [x] **F6 Shared pieces.** One `THEMES/PENS/MARKERS` module, one `Icon`
  module for repeated SVGs, `BookCard` in LibraryView, one "Asked as / Read as"
  parser; Reader `markQuote` fallback uses `anchor.ts`.
- [x] **F7 Strip web comments** in `web/app`, `web/components`, `web/lib`,
  config files.
  - Accept (F1–F7): `tsc` 0 errors, `next build` OK, frontend rule tests OK,
    Chrome smoke (open book, select → Explain → stream, citation jump,
    highlight persists after reload) when Chrome is available.

### Checkpoint F
- [x] Gate + build + Chrome smoke green; checkpoint review PASS (fixed: stream lost on book switch, dead onOpen, empty catches); pushed.

## Phase 4: Docs (after Phases 1–3)

- [x] **D1 `AGENTS.md`.** Also group root docs: `README.md` and `AGENTS.md` stay at the root; `GOAL.md` and `GLOSSARY.md` move to `docs/` (content unchanged; update every link). Rewrite to ~10–15K: hard rules, artifacts policy,
  verify commands, one short current-state block. Merge BUILD_PLAN's contract,
  ingest/retrieval/generation/figure rules; `git mv BUILD_PLAN.md archive/`.
  Keep the constitution copy in sync with `GOAL.md`. `web/AGENTS.md` checked.
- [x] **D2 `README.md`.** Rewrite: what it is, quickstart (Ollama,
  `setup_models.py --install`, UI import or `ingest.py`, `launch.py --open` /
  dev mode), tests, contract, repo-relative links only; carry over the
  useful Mac notes from the removed SETUP-MACOS.md (git history: python.org
  `Install Certificates.command`, `lsof` port check, why not Docker).
  `web/README.md` run-it section and file map updated.
- [ ] **D3 Engineering docs.** `docs/ENGINEERING.md` (architecture + why, no
  dated numbers, current module names, mermaid), `docs/DECISIONS.md` finalized,
  `GLOSSARY.md` definitions only, `.agents/skills/book-companion-ui/SKILL.md`
  current, `artifacts/README.md` index of kept files only,
  `artifacts/plans/backlog.md` (figure understanding, conversational clarify,
  caption quoting, "Needs owner" items).
  - Accept (D1–D3): 0 `file:///` links, 0 refs to missing files (script check),
    0 `smallbook_*` as default, every command in README run once and works.

## Phase 5: Final

- [ ] **Z Final gate.** Live gate, timing after vs before (report table),
  success-criteria checklist from `SPEC.md` with evidence, `git mv SPEC.md tasks archive/`,
  final summary in the last commit message, push.

## Needs owner

(Items that would change engine output, deletions, `vendor/`, `GOAL.md`.)

- `_reground_alphanumeric_quote` and `_TYPE_2_RE`/`_S3_RE`/`_IOPS_RE`/`_SLA_SLO_RE`
  hard-code this book's terms (breaks the "generalize" hard rule). Kept; removal
  changes output.
- The default book id `fde` is hard-coded outside the guarded logic modules:
  `engine/server.py` (`DEFAULT_BOOK_ID`, built with `"".join` to dodge the
  guard) and `engine/ingest.py` (`book_id == "fde"` picks `data/index.json`).
  Making the default book configurable changes paths and the catalog, so it
  is left as is.
- No test checks that the real answer-mode `SYSTEM` draft is held from the
  stream (the old `fake_respond` name hook only ever held the fake). E7 kept
  production behaviour identical (the draft streams live); whether it should
  be held is a product decision.
